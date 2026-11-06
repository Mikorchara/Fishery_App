"""Continuous process consent: synthetic files only, no credentials/network."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.qq_bot.management_config import ROOT,load_request,check_request
from apps.qq_bot.management_cli import initialize_demo,configure_existing
from apps.qq_bot.management_configuration_bridge import QQConfigurationBridge
from apps.qq_bot.management_limits import ManagementRunLimits
from apps.qq_bot.management_run import ManagementLedger,ManagementRun
from apps.qq_bot.contracts import BotError
from apps.qq_bot.trial_configuration import read_json


class ContinuousLedgerTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(dir=ROOT/'outputs/test-tmp');self.addCleanup(temp.cleanup)
        self.directory=Path(temp.name);self.clock=datetime(2026,1,1,tzinfo=timezone.utc);self.mono=0
        self.ledger=ManagementLedger(self.directory,scope_sha256='a'*64,bindings_sha256='b'*64,
            limits=ManagementRunLimits.continuous_run(),clock=lambda:self.clock,monotonic=lambda:self.mono,
            contract='management-qq-continuous-run@1')
        self.addCleanup(self.ledger.close);self.ledger.approve(self.ledger.plan(),confirmed=True)

    def reserve(self,key):
        return self.ledger.reserve(message_key=key,fingerprint=key,member_id='member-a',
            instance_id='management-isolated',device_id='sim-pond-1',app_id='123456789',group_id='group-a')

    def test_no_cumulative_expiry_count_or_cost_and_bounded_ram(self):
        for n in range(75):
            lease=self.reserve(str(n));self.ledger.check_lease(lease);self.ledger.release_lease(lease)
            self.clock+=timedelta(hours=1);self.mono+=3600
        self.ledger.check();self.assertEqual(self.ledger.report()['consumed_turns'],75)
        self.assertEqual(self.ledger._messages,{});self.assertEqual(self.ledger._bytes,b'')
        self.assertEqual(len(self.ledger.authority._issued),0)
        self.assertIsNone(self.ledger.report()['max_turns'])
        self.assertEqual(len(list((self.directory/'messages').iterdir())),75)

    def test_each_lease_still_expires_and_released_lease_is_invalid(self):
        lease=self.reserve('a');self.clock+=timedelta(seconds=91)
        with self.assertRaisesRegex(BotError,'RUN_TURN_EXPIRED'):self.ledger.check_lease(lease)
        self.ledger.release_lease(lease)
        with self.assertRaisesRegex(BotError,'INVALID_RUN_TURN_LEASE'):self.ledger.check_lease(lease)

    def test_duplicate_survives_ram_release_and_fsync_failure_halts(self):
        lease=self.reserve('a');self.ledger.release_lease(lease)
        with self.assertRaisesRegex(BotError,'RUN_MESSAGE_ALREADY_USED'):self.reserve('a')
        self.assertEqual(self.ledger.report()['consumed_turns'],1)
        with patch('apps.qq_bot.run_consent.os.fsync',side_effect=OSError()):
            with self.assertRaisesRegex(BotError,'RUN_LEDGER_FAILED'):self.reserve('b')
        with self.assertRaisesRegex(BotError,'RUN_LEDGER_FAILED'):self.reserve('c')

    def test_continuous_not_encoded_as_old_approval(self):
        with self.assertRaisesRegex(BotError,'INVALID_CONTINUOUS_RUN_LIMITS'):
            ManagementRunLimits(mode='continuous')
        with self.assertRaisesRegex(BotError,'INVALID_RUN_LIMITS'):
            ManagementRunLimits(None,None,None)

    def test_gateway_continuous_has_no_total_deadline_and_keeps_retry_cap(self):
        from apps.qq_bot.tests.test_gateway import GatewayTests
        fixture=GatewayTests();fixture.setUp();gateway=fixture.gateway
        seen=[]
        def pump(socket,guard):
            seen.append(gateway._deadline);gateway.stop.set()
        socket=unittest.mock.MagicMock()
        gateway.connector=lambda _:socket
        with patch.object(gateway,'_pump',pump):gateway.run_until_stopped()
        self.assertEqual(seen,[None]);self.assertNotIn('QQ_RUN_DURATION_REACHED',fixture.codes)
        gateway=fixture.make(connector=lambda _:(_ for _ in ()).throw(OSError()))
        with patch.object(gateway.stop,'wait',return_value=False):
            with self.assertRaisesRegex(BotError,'QQ_RECONNECT_LIMIT'):gateway.run_until_stopped()
        self.assertFalse(gateway._worker.is_alive())


class ConfigurationBridgeTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(dir=ROOT/'outputs/test-tmp');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.data=self.root/'instance';self.cfg=self.root/'config'
        initialize_demo(self.data,self.cfg,app_id='123456789',group_id='group-a',members=('member-a',),enable=True)
        self.bridge=QQConfigurationBridge(ROOT,self.data,self.cfg)
        self.settings=dict(enabled=True,ai_enabled=True,app_id='123456789',group_id='group-a',
            members=['member-a'],max_output_tokens=4096,event_notifications_enabled=False)

    def apply(self):
        return self.bridge.apply(self.settings,expected_revision=self.bridge.read_nonsecret()['revision'])

    def test_continuous_scope_frozen_tokens_and_no_database_or_network(self):
        before={name:(self.data/name).read_bytes() for name in ('monitoring.sqlite3','knowledge.sqlite3')}
        with patch('sqlite3.connect',side_effect=AssertionError('no SQL')),\
                patch('socket.socket.connect',side_effect=AssertionError('no network')):
            result=self.apply();request,summary=check_request(self.cfg/'request.json',offline=True)
        self.assertEqual(result['settings']['max_output_tokens'],4096)
        self.assertTrue(request.continuous);self.assertIsNone(summary['limits']['seconds'])
        self.assertEqual(read_json(self.cfg/'request.json')['schema_version'],3)
        self.assertTrue(request.web_agent);self.assertEqual(summary['agent_mode'],'web')
        self.assertEqual(summary['contract'],'management-qq-web-agent-run@1')
        self.assertCountEqual(summary['tools'],['get_current_water_quality','search_fishery_knowledge',
            'get_water_quality_history','score_current_water_quality'])
        self.assertEqual(summary['max_model_requests_per_turn'],3)
        self.assertEqual(summary['output_tokens_per_request'],4096)
        self.assertTrue(list(self.root.glob('.qq-config-previous-*')))
        self.assertEqual(before,{name:(self.data/name).read_bytes() for name in before})

    def test_explicit_legacy_schema2_continuous_contract_remains_current_only(self):
        legacy=self.root/'legacy-continuous'
        path=configure_existing(self.data,legacy,app_id='123456789',group_id='group-a',members=('member-a',),
            enable=True,continuous=True,output_tokens=4096)
        with patch('sqlite3.connect',side_effect=AssertionError('no SQL')),\
                patch('socket.socket.connect',side_effect=AssertionError('no network')):
            request,summary=check_request(path,offline=True)
        self.assertEqual(read_json(path)['schema_version'],2)
        self.assertTrue(request.continuous);self.assertFalse(request.web_agent)
        self.assertEqual(summary['contract'],'management-qq-continuous-run@1')
        self.assertEqual(summary['agent_mode'],'current')
        self.assertEqual(summary['tools'],['get_current_water_quality'])
        self.assertEqual(summary['max_model_requests_per_turn'],2)
        self.assertEqual(summary['output_tokens_per_request'],4096)

    def test_ai_disabled_separate_from_bot_and_runtime_does_not_enable(self):
        self.settings['ai_enabled']=False;self.apply()
        request=load_request(self.cfg/'request.json');run=self.root/'run';run.mkdir()
        with patch('apps.qq_bot.management_run.ManagementRun._turn_credentials',side_effect=AssertionError('no key')):
            host=ManagementRun(request,run,async_client_factory=lambda **kw:None)
            try:
                self.assertFalse(host.config.enabled);self.assertTrue(request.enabled)
                host.approve(host.plan(),confirmed=True);host.check()
            finally:host.close()

    def test_conflict_recipient_and_token_rejections(self):
        old=self.bridge.read_nonsecret()['revision'];self.apply()
        with self.assertRaisesRegex(BotError,'QQ_SETTINGS_CONFLICT'):
            self.bridge.apply(self.settings,expected_revision=old)
        self.settings['event_notifications_enabled']=True
        with self.assertRaisesRegex(BotError,'EVENT_RECIPIENT_BINDING_REQUIRED'):self.apply()
        self.settings['event_notifications_enabled']=False;self.settings['max_output_tokens']=4097
        with self.assertRaises(Exception):self.apply()

    def test_changed_scope_or_token_cannot_reuse_request(self):
        self.apply();request=read_json(self.cfg/'request.json')
        import json
        request['scope_sha256']='0'*64
        (self.cfg/'request.json').write_text(json.dumps(request),encoding='utf-8')
        with self.assertRaisesRegex(BotError,'MANAGEMENT_SCOPE_REVIEW_REQUIRED'):load_request(self.cfg/'request.json')

    def test_notification_toggle_retains_binding_but_app_change_does_not(self):
        from apps.ai_backend.secure_files import write_private
        from apps.qq_bot.event_recipients import recipient_ref,CONTRACT
        import json
        recipient=self.cfg/'recipient.json'
        write_private(recipient,(json.dumps(dict(contract=CONTRACT,app_id='123456789',user_openid='user-a',
            user_ref=recipient_ref('123456789','user-a'),active_probe_sha256='a'*64))+'\n').encode())
        request=read_json(self.cfg/'request.json');request['event_recipient_file']=str(recipient)
        (self.cfg/'request.json').write_text(json.dumps(request),encoding='utf-8')
        self.settings['event_notifications_enabled']=True;self.apply()
        self.settings['event_notifications_enabled']=False;state=self.apply()
        self.assertTrue(state['recipient_available']);self.assertFalse(state['settings']['event_notifications_enabled'])
        self.assertIn('verified_recipient_file',read_json(self.cfg/'request.json'))
        self.settings['event_notifications_enabled']=True;state=self.apply()
        self.assertTrue(state['settings']['event_notifications_enabled'])
        self.settings['app_id']='987654321'
        with self.assertRaisesRegex(BotError,'EVENT_RECIPIENT_BINDING_REQUIRED'):self.apply()
        self.settings['event_notifications_enabled']=False;state=self.apply()
        self.assertFalse(state['recipient_available']);self.assertFalse((self.cfg/'recipient.json').exists())


if __name__=='__main__':unittest.main()
