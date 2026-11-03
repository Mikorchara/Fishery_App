"""Management-owned active notification tests. New SIMULATOR stores + memory HTTP."""
from contextlib import redirect_stdout
from io import StringIO
from datetime import datetime,timedelta,timezone
import json
from unittest.mock import patch
import unittest

import httpx
from apps.ai_backend.secure_files import write_private
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from apps.qq_bot.contracts import BotError
from apps.qq_bot.management_run import ManagementRun
from apps.qq_bot.management_config import load_request,check_request
from apps.qq_bot.live_transport import LiveQQAPI
from apps.qq_bot.event_notifications import NotificationPermit,NoticeJournal,EventNotifier
from apps.qq_bot.event_recipients import prepare_recipient,load_recipient,recipient_ref,PROBE
from apps.qq_bot.tests import test_management_live as fixture


def binding(root):
    proof=root/'proof';proof.mkdir();ref=recipient_ref('123456789','private-user')
    recipient=dict(contract=PROBE,app_id='123456789',user_openid='private-user',user_ref=ref,
                   status='PROBE_RECIPIENT_ONLY',business_access=False)
    result=dict(contract=PROBE,mode='active_once',code='QQ_PRIVATE_ACTIVE_API_ACCEPTED',
        api_accepted=True,operator_approved_active=True,message_submissions=1,proactive_messages=1,
        report_saved=True,recipient_saved=True,user_ref=ref)
    for name,value in [('recipient.json',recipient),('result.json',result)]:
        write_private(proof/name,json.dumps(value).encode())
    path=root/'recipient.json';prepare_recipient(proof,path);return path


class PrivateNoticeTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.ManagementLiveTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.now=datetime.now(timezone.utc);self.seconds=0;self.posts=[]
        self.binding=binding(self.case.root);self.connected=True
        self.writer=MonitoringService(MonitoringRepository(self.case.root/'instance/monitoring.sqlite3'),clock=lambda:self.now)
        self.sim=Simulator(start=self.now-timedelta(seconds=10),session_id='private-notice-test')
        self.ingest(4.2)

    def ingest(self,oxygen):
        packet=self.sim.advance();self.now=datetime.fromisoformat(packet['timestamp'])
        packet['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=oxygen,min=oxygen,max=oxygen,latest=oxygen)
        self.writer.ingest(packet);self.seconds+=10

    def compose(self,approve=True):
        directory=self.case.root/'notice-run';directory.mkdir()
        self.host=ManagementRun(self.case.request,directory,async_client_factory=self.case.factory,clock=lambda:self.now)
        self.addCleanup(self.host.close);self.host.enable_event_notifications(self.binding)
        if not approve:return
        self.host.approve(self.host.plan(),confirmed=True)
        self.outcome='ACCEPTED'
        def http(request):
            self.posts.append(request)
            if self.outcome=='UNKNOWN':raise httpx.ReadTimeout('fake',request=request)
            if self.outcome=='DENIED':return httpx.Response(400,json={'code':40034105,'message':'private detail'})
            return httpx.Response(200,json={'id':'accepted'})
        client=httpx.Client(transport=httpx.MockTransport(http));self.addCleanup(client.close)
        self.api=LiveQQAPI('123456789',None,permit=self.host.permit,client=client)
        self.api._token='fictional';self.api._expires=self.api._now()+3600
        self.permit=NotificationPermit(self.host)
        self.journal=NoticeJournal(self.case.root,self.permit.audience,clock=lambda:self.now)
        self.notifier=EventNotifier(self.permit,self.api,self.journal,connected=lambda:self.connected,
            clock=lambda:self.now,monotonic=lambda:self.seconds)
        self.addCleanup(self.notifier.close)

    def test_new_upgrade_recovery_only_private_zero_model_readonly(self):
        self.compose();path=self.case.root/'instance/monitoring.sqlite3';before=path.read_bytes()
        self.notifier.tick();self.notifier.tick();self.assertEqual(path.read_bytes(),before)
        self.ingest(2.2);self.notifier.tick();self.ingest(6.4);self.notifier.tick()
        self.assertEqual(len(self.posts),3)
        self.assertTrue(all(p.url.path=='/v2/users/private-user/messages' for p in self.posts))
        self.assertTrue(all(set(json.loads(p.content))=={'msg_type','content'} for p in self.posts))
        self.assertEqual(self.case.http,[]);self.assertEqual(self.host.ledger.report()['consumed_turns'],0)

    def test_no_approval_or_forged_permission_zero_post(self):
        self.compose(False)
        with self.assertRaises(BotError):NotificationPermit(self.host)
        self.assertEqual(self.posts,[])

    def test_unknown_never_retried_even_after_restart(self):
        self.compose();self.outcome='UNKNOWN'
        with self.assertRaisesRegex(BotError,'QQ_DELIVERY_UNKNOWN'):self.notifier.tick()
        self.assertEqual(list(self.journal.states.values()),['UNKNOWN'])
        self.notifier.close()
        journal=NoticeJournal(self.case.root,self.permit.audience,clock=lambda:self.now)
        notifier=EventNotifier(self.permit,self.api,journal,connected=lambda:True,clock=lambda:self.now)
        self.addCleanup(notifier.close);notifier.tick();self.assertEqual(len(self.posts),1)

    def test_changed_recipient_disconnect_and_revoked_request_refuse(self):
        self.compose();self.connected=False;self.notifier.tick();self.assertEqual(self.posts,[])
        self.connected=True
        with patch.object(self.host,'_check_configuration',side_effect=BotError('RUN_BINDINGS_CHANGED')):
            with self.assertRaises(BotError):self.notifier.tick()
        self.binding.write_text('{}')
        with self.assertRaises(BotError):self.notifier.tick()
        self.assertEqual(self.posts,[])

    def test_journal_fsync_failure_prevents_send(self):
        self.compose()
        with patch('apps.qq_bot.event_notifications.os.fsync',side_effect=OSError('fake')):
            with self.assertRaisesRegex(BotError,'JOURNAL_FAILED'):self.notifier.tick()
        self.assertEqual(self.posts,[])

    def test_platform_permission_error_is_numeric_and_no_retry(self):
        self.compose();self.outcome='DENIED'
        with self.assertRaisesRegex(BotError,'QQ_API_40034105'):self.notifier.tick()
        self.seconds+=20;self.notifier.tick();self.assertEqual(len(self.posts),1)
        self.assertEqual(list(self.journal.states.values()),['FAILED'])

    def test_acceptance_preserved_if_checkpoint_fails(self):
        self.compose()
        with patch.object(self.journal,'finish',side_effect=BotError('JOURNAL_FAILED')):
            with self.assertRaises(BotError):self.notifier.tick()
        self.assertEqual(self.notifier.report()['accepted'],1)
        self.assertEqual(list(self.journal.states.values()),['CLAIMED'])

    def test_expiry_rejects_new_notice_without_renewing_permission(self):
        self.compose();self.host.ledger._deadline=self.host.now()-1
        with self.assertRaisesRegex(BotError,'RUN_EXPIRED'):self.notifier.tick()
        self.assertEqual(self.posts,[])

    def test_request_explicit_binding_check_no_db_key_network(self):
        value=json.loads(self.case.path.read_text());value['event_recipient_file']=str(self.binding)
        path=self.case.root/'notice-request.json';path.write_text(json.dumps(value))
        with patch('sqlite3.connect',side_effect=AssertionError('database')),\
                patch('socket.getaddrinfo',side_effect=AssertionError('network')):
            request,summary=check_request(path,offline=True)
        self.assertEqual(summary['event_notifications']['destination'],'VERIFIED_PRIVATE_RECIPIENT_ONLY')
        self.assertNotIn('private-user',json.dumps(summary))
        self.assertIsNone(check_request(self.case.path,offline=True)[1]['event_notifications'])

    def test_bound_recipient_is_create_only_and_cross_app_refused(self):
        before=self.binding.read_bytes()
        with self.assertRaisesRegex(BotError,'TARGET_EXISTS'):prepare_recipient(self.case.root/'proof',self.binding)
        self.assertEqual(before,self.binding.read_bytes())
        with self.assertRaises(BotError):load_recipient(self.binding,'999999999')

    def test_report_includes_notification_status(self):
        self.compose();self.notifier.tick();self.notifier.close()
        self.host._notice_report=self.notifier.report();report=self.host.report()
        self.assertEqual(report['event_notifications']['accepted'],1)
        self.assertFalse(report['event_notifications']['client_display_confirmed'])

    def test_offline_cli_notification_lifecycle_and_final_report(self):
        from apps.qq_bot.management_cli import run
        value=json.loads(self.case.path.read_text());value['event_recipient_file']=str(self.binding)
        path=self.case.root/'notice-request.json';path.write_text(json.dumps(value))
        statuses=[];directory=self.case.root/'cli-run'
        with patch('apps.qq_bot.event_notifications.POLL_SECONDS',.01):
            code=run(path,directory,offline=True,seconds=30,
                stop_requested=lambda:'QQ_EVENT_NOTICE_API_ACCEPTED' in statuses,
                emit_status=lambda code,**_:statuses.append(code))
        self.assertEqual(code,0,statuses)
        report=json.loads((directory/'result.json').read_text())
        self.assertEqual(report['event_notifications']['accepted'],1)
        self.assertEqual(report['event_notifications']['destination'],'private')
        self.assertEqual(report['event_notifications']['state'],'CLOSED')

    def test_identity_templates_and_prompt_match_product_role(self):
        from apps.qq_bot.hybrid_intent import classify
        from apps.ai_service.channel_hybrid import INSTRUCTION,PROMPT_ID
        self.assertEqual(classify('你是谁？').kind,'identity')
        self.assertIn('鳗鲡养殖智能体',classify('你好').text)
        self.assertIn('鳗鲡养殖智能体',INSTRUCTION);self.assertEqual(PROMPT_ID,'QQ_HYBRID_DIALOGUE@3')
        self.assertEqual(self.case.http,[])
