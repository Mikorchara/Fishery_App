"""Attach QQ config to synthetic daily data without changing that data or I/O."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
from io import StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.management_paths import ManagementPaths
from apps.management_web.instance import initialize_instance
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from apps.ai_service.channel_management_live import prepared_scope, preparation_record
from apps.qq_bot.conversations import ConversationOptions
from apps.qq_bot.contracts import BotError
from apps.qq_bot import management_cli as cli
from apps.qq_bot.management_config import MARKER, ROOT, check_request
from apps.qq_bot.trial_configuration import write_new


class ConfigureExistingTests(unittest.TestCase):
    def setUp(self):
        parent=ROOT/'outputs/test-tmp';parent.mkdir(parents=True,exist_ok=True)
        temporary=TemporaryDirectory(dir=parent);self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.instance=self.root/'daily';self.config=self.root/'qq-config'
        self.paths=ManagementPaths.resolve(ROOT,data_root=self.instance)
        initialize_instance(self.paths)
        self.marker=dict(contract=MARKER,root=str(self.instance.resolve()),
            instance_id='management-isolated',device_id='sim-pond-1',source='SIMULATOR')
        write_new(self.instance/'qq-isolated-instance.json',self.marker)
        # Existing observations, settings, Web authorization and trace are owned
        # by this fixture and must remain byte-for-byte intact during attachment.
        now=datetime.now(timezone.utc)
        service=MonitoringService(MonitoringRepository(self.paths.monitoring),clock=lambda:now)
        simulator=Simulator(start=now-timedelta(seconds=30),device_id='sim-pond-1',session_id='existing-test')
        for _ in range(3):service.ingest(simulator.advance())
        self.paths.settings.write_text('{"fixture":"keep-settings"}',encoding='utf8')
        (self.paths.policy_directory/'keep.json').write_text('{"fixture":"keep-web-policy"}',encoding='utf8')
        self.paths.traces.write_text('fictional-keep-trace\n',encoding='utf8')
        self.before=self.hashes(self.instance)

    @staticmethod
    def hashes(directory):
        return {str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in directory.rglob('*') if p.is_file()}

    def configure(self,**kwargs):
        values=dict(app_id='123456789',group_id='fixture-group',members=('fixture-member',),enable=True)
        values.update(kwargs)
        return cli.configure_existing(self.instance,self.config,**values)

    def test_attach_valid_instance_is_read_only_and_preserves_every_source_file(self):
        original_connect=sqlite3.connect
        uris=[]
        def read_only(database,*args,**kwargs):
            self.assertTrue(kwargs.get('uri'))
            self.assertIn('?mode=ro',str(database))
            uris.append(str(database))
            return original_connect(database,*args,**kwargs)
        with patch('sqlite3.connect',side_effect=read_only),\
             patch('apps.ai_backend.credentials.CredentialStore.resolve',side_effect=AssertionError('secret')) ,\
             patch('apps.qq_bot.management_cli.private_project_location',side_effect=AssertionError('private store')),\
             patch('socket.socket.connect',side_effect=AssertionError('network')),\
             patch('socket.getaddrinfo',side_effect=AssertionError('network')):
            request=self.configure()
        self.assertEqual(len(uris),2)
        self.assertEqual(self.before,self.hashes(self.instance))
        value=json.loads(request.read_text(encoding='utf8'))
        self.assertTrue(value['enabled'])
        self.assertNotIn('event_recipient_file',value)
        self.assertEqual(value['members'],['fixture-member'])
        self.assertEqual(value['schema_version'],2)
        self.assertEqual(value['limits']['mode'],'continuous')
        for name in ('max_turns','seconds','total_budget_cny'):
            self.assertIsNone(value['limits'][name])
        access=json.loads((self.config/'access.json').read_text(encoding='utf8'))
        self.assertEqual(access['groups'][0]['capabilities'],['current'])
        monitoring=json.loads((self.config/'monitoring.json').read_text(encoding='utf8'))
        self.assertEqual(monitoring['data_root'],str(self.instance.resolve()))
        # A synthetic preparation record binds current source while the root
        # agent refreshes the tracked candidate only after every edit is frozen.
        preparation=self.root/'preparation.json'
        scope=prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True))
        write_new(preparation,preparation_record(scope))
        with patch('apps.qq_bot.management_config.PREPARATION',preparation),\
             patch('sqlite3.connect',side_effect=AssertionError('check must not open database')),\
             patch('apps.ai_backend.credentials.CredentialStore.resolve',side_effect=AssertionError('secret')),\
             patch('socket.getaddrinfo',side_effect=AssertionError('network')):
            _,summary=check_request(request,offline=True)
        self.assertFalse(summary['database_opened'])
        self.assertFalse(summary['credential_checked'])
        self.assertEqual(summary['network_requests'],0)
        self.assertEqual(self.before,self.hashes(self.instance))

    def test_explicit_bounded_configuration_retains_legacy_five_turn_contract(self):
        request=self.configure(continuous=False)
        value=json.loads(request.read_text(encoding='utf8'))
        self.assertEqual(value['schema_version'],1)
        self.assertEqual(value['limits']['max_turns'],5)
        self.assertEqual(value['limits']['seconds'],1800)
        self.assertEqual(value['limits']['total_budget_cny'],'8.06')
        self.assertEqual(self.before,self.hashes(self.instance))
        _,summary=check_request(request,offline=True)
        self.assertEqual(summary['contract'],'management-qq-hybrid-process-run@1')
        self.assertFalse(summary['database_opened'])

    def test_default_request_remains_disabled_and_repeat_does_not_overwrite(self):
        request=self.configure(enable=False)
        self.assertFalse(json.loads(request.read_text())['enabled'])
        configured=self.hashes(self.config)
        with self.assertRaisesRegex(BotError,'INITIALIZATION_TARGET_EXISTS'):
            self.configure()
        self.assertEqual(configured,self.hashes(self.config))
        self.assertEqual(self.before,self.hashes(self.instance))
        # Existing prepare-demo must still refuse existing data, not attach.
        with self.assertRaisesRegex(BotError,'INITIALIZATION_TARGET_EXISTS'):
            cli.initialize_demo(self.instance,self.root/'different-config',
                app_id='123456789',group_id='fixture-group',members=('fixture-member',))

    def test_missing_or_wrong_marker_does_not_create_configuration_or_repair(self):
        marker=self.instance/'qq-isolated-instance.json'
        marker.unlink()
        with self.assertRaisesRegex(BotError,'ISOLATED_INSTANCE_PROOF_REQUIRED'):self.configure()
        for field,value in (('source','REAL'),('root',str(self.root)),
                            ('instance_id','different'),('device_id','other-pond'),('contract','other')):
            with self.subTest(field=field):
                marker.write_text(json.dumps({**self.marker,field:value}),encoding='utf8')
                before=self.hashes(self.instance)
                with self.assertRaisesRegex(BotError,'ISOLATED_INSTANCE_PROOF_REQUIRED'):self.configure()
                self.assertEqual(before,self.hashes(self.instance))
        self.assertFalse(self.config.exists())

    def test_invalid_database_does_not_create_configuration_or_change_source(self):
        self.paths.monitoring.write_bytes(b'fictional corrupt sqlite')
        before=self.hashes(self.instance)
        with self.assertRaisesRegex(ValueError,'MONITORING_DATABASE_CORRUPT'):self.configure()
        self.assertEqual(before,self.hashes(self.instance))
        self.assertFalse(self.config.exists())

    def test_missing_database_is_not_created(self):
        self.paths.knowledge.unlink()
        before=self.hashes(self.instance)
        with self.assertRaisesRegex(ValueError,'KNOWLEDGE_DATABASE_MISSING'):self.configure()
        self.assertEqual(before,self.hashes(self.instance))
        self.assertFalse(self.paths.knowledge.exists())
        self.assertFalse(self.config.exists())

    def test_bad_paths_and_grants_fail_before_reading_or_creating_files(self):
        with patch.object(cli,'ROOT',self.root/'different-workspace'),\
             patch('sqlite3.connect',side_effect=AssertionError('database')):
            with self.assertRaisesRegex(BotError,'ISOLATED_OUTPUTS_DIRECTORY_REQUIRED'):self.configure()
        for kwargs in (dict(members=()),dict(members=('duplicate','duplicate')),dict(group_id='not valid'),dict(app_id='invalid')):
            with self.subTest(kwargs=kwargs),self.assertRaises(BotError):self.configure(**kwargs)
        self.assertEqual(self.before,self.hashes(self.instance))
        self.assertFalse(self.config.exists())

    def test_cli_attaches_existing_instance_and_requires_explicit_identities(self):
        output=StringIO()
        with redirect_stdout(output):
            code=cli.main(['configure-existing','--data-root',str(self.instance),
                '--config-directory',str(self.config),'--app-id','123456789',
                '--group-id','fixture-group','--member','fixture-member'])
        self.assertEqual(code,0)
        self.assertEqual(json.loads(output.getvalue())['code'],'MANAGEMENT_EXISTING_INSTANCE_CONFIGURED')
        self.assertEqual(self.before,self.hashes(self.instance))
        with patch('sys.stderr',new_callable=StringIO),self.assertRaises(SystemExit) as missing:
            cli.main(['configure-existing','--data-root',str(self.instance),
                      '--config-directory',str(self.root/'missing-identities')])
        self.assertEqual(missing.exception.code,2)


if __name__=='__main__':unittest.main()
