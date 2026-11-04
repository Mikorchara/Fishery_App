"""Typed live composition, exclusively memory HTTP and synthetic new instances."""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

import httpx
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel_management_live import LivePermit, ManagementLiveTurn
from apps.qq_bot.management_config import ROOT, load_request, check_request
from apps.qq_bot.management_cli import initialize_demo, run
from apps.qq_bot.management_run import ManagementRun
from apps.qq_bot.live_transport import LiveQQAPI, LiveQQTransport, live_connector
from apps.qq_bot.ai_coordinator import QQAICoordinator
from apps.qq_bot.ai_scheduler import QQAIJobScheduler
from apps.qq_bot.ai_routing import OfflineQQAIRouter
from apps.qq_bot.adapter import QQAdapter
from apps.qq_bot.service import ReadOnlyQueries
from apps.qq_bot.gateway import QQGateway
from apps.qq_bot.contracts import BotError
from apps.qq_bot.demo_runtime import FakeSocket
from apps.qq_bot.tests import test_hybrid as fixture


class ManagementLiveTests(unittest.TestCase):
    factory=fixture.HybridRunTests.factory

    def setUp(self):
        temp=TemporaryDirectory(dir=ROOT/'outputs/test-tmp');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.http=[];self.started=threading.Event()
        self.mode='general';self.general_text='溶解氧是溶解在水中的氧气。'
        self.path=initialize_demo(self.root/'instance',self.root/'config',app_id='123456789',group_id='group-a',
            members=('member-a','member-b'),enable=True)
        self.request=load_request(self.path);self.outcomes=['ACCEPTED']*10;self.posts=[];self.seq=0
        self.addCleanup(patch.stopall)
        for target in ('socket.socket.connect','socket.getaddrinfo'):
            patch(target,side_effect=AssertionError('no real network')).start()
        from apps.ai_backend.tests import test_execution
        test_execution.ExecutionTests.setUp(self)  # Permit only asyncio's private loopback wakeup socket.
        from apps.ai_backend.credentials import CredentialStore
        original=CredentialStore.resolve
        def memory_only(store,*args,**kwargs):
            if store.private_location is not None or store.project_env_path is not None or type(store._process_env) is not dict:
                raise AssertionError('no real credentials')
            return original(store,*args,**kwargs)
        patch.object(CredentialStore,'resolve',memory_only).start()

    def compose(self,approve=True,*,failure_feedback=False):
        directory=self.root/'run';directory.mkdir()
        self.host=ManagementRun(self.request,directory,async_client_factory=self.factory)
        self.addCleanup(self.host.close)
        if approve:self.host.approve(self.host.plan(),confirmed=True)
        if not approve:return
        def qq(request):
            self.posts.append(json.loads(request.content));outcome=self.outcomes.pop(0)
            if outcome=='UNKNOWN':raise httpx.ReadTimeout('fake unknown',request=request)
            if outcome=='FAILED':return httpx.Response(503,json={})
            return httpx.Response(200,json={'id':'fake-accepted'})
        self.client=httpx.Client(transport=httpx.MockTransport(qq),trust_env=False,follow_redirects=False)
        self.addCleanup(self.client.close)
        self.api=LiveQQAPI('123456789',None,permit=self.host.permit,client=self.client)
        self.api._token='fictional';self.api._expires=time.monotonic()+1000
        self.transport=LiveQQTransport(self.api,self.host);self.addCleanup(self.transport.close)
        self.coordinator=QQAICoordinator(self.host.access,self.host.monitoring,self.host.base_service,
            config=self.host.config,conversations=self.host.store,session_run=self.host)
        self.scheduler=QQAIJobScheduler(self.coordinator,self.transport,failure_feedback=failure_feedback);self.addCleanup(self.scheduler.close)
        adapter=QQAdapter(self.host.access,ReadOnlyQueries(self.host.monitoring),mode='QQ_PASSIVE_READY')
        self.router=OfflineQQAIRouter(adapter,self.scheduler);self.addCleanup(self.router.close)
        self.gateway=QQGateway('123456789',self.api,adapter,trial_router=self.router,
            connector=lambda _:FakeSocket('123456789','group-a','member-a'),emit=lambda *_a,**_k:None)
        self.router.connected()

    def receive(self,text='什么是溶解氧？',member='member-a',message_id=None):
        self.seq+=1
        packet=dict(op=0,t='GROUP_AT_MESSAGE_CREATE',s=self.seq,d=dict(id=message_id or 'msg-'+str(self.seq),
            group_openid='group-a',author=dict(member_openid=member,bot=False),
            timestamp=datetime.now(timezone.utc).isoformat(),content=text))
        self.gateway._dispatch_authenticated(packet)
        raw,_,proof=self.gateway._queue.get_nowait();self.gateway._queue.task_done()
        return self.router.receive(raw,transport_app_id='123456789',mention=proof)

    def ask(self,text='什么是溶解氧？'):
        code,task=self.receive(text);self.assertEqual(code,'AI_ADMITTED')
        return self.scheduler.wait(task,95)

    def test_general_water_mixed_history_and_actual_http_budget(self):
        self.compose();before=(self.root/'instance/monitoring.sqlite3').read_bytes()
        for mode in ('general','general','water','water','general'):
            self.mode=mode;done=self.ask('现在水质如何？' if mode=='water' else '一般解释溶解氧')
            self.assertEqual(done['history_code'],'HISTORY_COMMITTED')
        self.assertEqual(len(self.http),7);self.assertEqual(len(self.posts),5)
        self.assertEqual(self.host.ledger.report()['consumed_turns'],5)
        self.assertEqual(self.host.store.counts()['turns'],5)
        self.assertEqual(sum(t['model_http_requests'] for t in self.host.turns),7)
        for entry in self.host.turns:
            self.assertTrue(entry['verified']);self.assertEqual(entry['sdk_resources']['state'],'CLOSED')
            self.assertTrue(entry['sdk_resources']['thread_exited'])
        self.assertEqual(before,(self.root/'instance/monitoring.sqlite3').read_bytes())

    def test_unapproved_copied_or_old_fake_permit_never_opens_io(self):
        self.compose(approve=False)
        with self.assertRaises(Exception):self.host.check()
        with self.assertRaises(Exception):LiveQQAPI('123456789',None,permit={})
        self.assertEqual(self.http,[])
        self.host.approve(self.host.plan(),confirmed=True)
        forged=replace(self.host.permit,nonce=object())
        with self.assertRaisesRegex(Exception,'MANAGEMENT_RUN_PERMIT_REQUIRED'):forged.check()
        with self.assertRaisesRegex(Exception,'MANAGEMENT_NETWORK_PERMIT_REQUIRED'):live_connector(self.host.permit)
        with self.assertRaisesRegex(Exception,'MANAGEMENT_QQ_IO_MODE_MISMATCH'):
            LiveQQAPI('123456789',None,permit=self.host.permit)

    def test_unknown_delivery_no_resend_no_history_and_no_refund(self):
        self.compose();self.outcomes[0]='UNKNOWN'
        done=self.ask()
        self.assertEqual(done['state'],'DELIVERY_UNKNOWN');self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertEqual((len(self.http),len(self.posts)),(1,1))
        self.assertEqual(self.host.ledger.report()['consumed_turns'],1)

    def test_clear_unknown_member_and_duplicate_preserve_quota(self):
        self.compose();self.ask();before=self.host.ledger.report()['consumed_turns']
        self.assertEqual(self.receive('/清空会话')[0],'QQ_REPLY_API_ACCEPTED')
        self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertNotEqual(self.receive(member='outsider')[0],'AI_ADMITTED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],before)

    def test_config_change_or_sdk_quarantine_halts_without_more_io(self):
        self.compose();self.ask()
        with patch('apps.qq_bot.session_run.SDK_RESOURCES.assert_healthy',side_effect=GatewayError('SDK_RESOURCE_QUARANTINED')):
            with self.assertRaises(Exception):self.host.check()
        self.assertNotEqual(self.receive()[0],'AI_ADMITTED');self.assertEqual(len(self.http),1)

    def test_check_has_no_database_key_network_or_approval(self):
        before=set(self.root.rglob('*'))
        with patch('sqlite3.connect',side_effect=AssertionError('database')):
            request,result=check_request(self.path,offline=True)
        self.assertFalse(result['credential_checked']);self.assertFalse(result['database_opened'])
        self.assertEqual(set(self.root.rglob('*')),before)

    def test_scope_budget_missing_config_and_real_instance_refused(self):
        original=json.loads(self.path.read_text())
        for field,value,code in (('scope_sha256','0'*64,'SCOPE'),('limits',dict(max_turns=5,seconds=1800,total_budget_cny='1'),'BUDGET')):
            altered={**original,field:value};p=self.root/(field+'.json');p.write_text(json.dumps(altered))
            with self.assertRaisesRegex(Exception,code):load_request(p)
        with self.assertRaises(Exception):load_request(self.root/'missing.json')
        with self.assertRaises(Exception):initialize_demo(self.root/'instance',self.root/'other',app_id='123456789',group_id='g',members=('m',))

    def test_ctrl_c_before_approval_and_report_failure_do_not_read_keys(self):
        # The live path is stopped at human approval; no SDK/Gateway construction.
        with patch('apps.qq_bot.management_config.version',return_value='15.0.1'):
            code=run(self.path,self.root/'interrupt',read=lambda _:(_ for _ in ()).throw(KeyboardInterrupt()),emit_status=lambda *_a,**_k:None)
        self.assertEqual(code,0)
        result=json.loads((self.root/'interrupt/result.json').read_text())
        self.assertEqual(result['quota']['consumed_turns'],0);self.assertTrue(result['ram_cleared'])

    def test_disabled_request_and_expiry_refuse_before_model(self):
        self.request=replace(self.request,enabled=False)
        self.compose(approve=False)
        with self.assertRaisesRegex(Exception,'AI_DISABLED'):self.host.approve(self.host.plan(),confirmed=True)
        self.assertEqual(self.http,[])

    def test_expired_permit_stops_new_sdk_and_does_not_restore_budget(self):
        self.compose();self.ask()
        self.host.ledger._deadline=time.monotonic()-1
        with self.assertRaisesRegex(Exception,'RUN_EXPIRED'):self.host.permit.check()
        self.assertNotEqual(self.receive()[0],'AI_ADMITTED')
        self.assertEqual((len(self.http),self.host.ledger.report()['consumed_turns']),(1,1))

    def test_ordinary_provider_failure_then_new_message_is_allowed(self):
        self.compose();self.mode='provider_error'
        self.assertEqual(self.ask()['state'],'FAILED')
        self.assertEqual(self.host.turns[0]['sdk_resources']['state'],'CLOSED')
        self.mode='general';self.assertEqual(self.ask()['history_code'],'HISTORY_COMMITTED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],2)

    def test_binding_or_scope_revocation_cancels_running_io(self):
        self.compose();self.mode='blocked'
        code,task=self.receive();self.assertEqual(code,'AI_ADMITTED');self.assertTrue(self.started.wait(5))
        self.coordinator.reconfigure(replace(self.coordinator.config,enabled=False))
        done=self.scheduler.wait(task,12)
        self.assertNotEqual(done['state'],'DELIVERED');self.assertEqual(self.posts,[])
        self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertEqual(self.host.turns[0]['sdk_resources']['state'],'CLOSED')

    def test_result_write_failure_is_explicit_and_does_not_retry(self):
        from apps.qq_bot import management_cli
        original=management_cli.write_new
        def fail_result(path,value):
            if path.name=='result.json':raise OSError('synthetic report failure')
            return original(path,value)
        statuses=[]
        with patch('apps.qq_bot.management_config.version',return_value='15.0.1'),patch.object(management_cli,'write_new',side_effect=fail_result):
            result=run(self.path,self.root/'report-failed',read=lambda _:(_ for _ in ()).throw(KeyboardInterrupt()),
                       emit_status=lambda code,**_:statuses.append(code))
        self.assertEqual(result,1);self.assertIn('MANAGEMENT_REPORT_OR_CLEANUP_FAILED',statuses)
        self.assertEqual(self.http,[])

    def test_declined_approval_does_not_start_provider_or_gateway(self):
        code=run(self.path,self.root/'declined',read=lambda _:'NO',emit_status=lambda *_a,**_k:None)
        self.assertEqual(code,1)
        report=json.loads((self.root/'declined/result.json').read_text())
        self.assertEqual(report['code'],'MANAGEMENT_APPROVAL_DECLINED')
        self.assertEqual(report['quota']['consumed_turns'],0);self.assertEqual(self.http,[])

    def test_invalid_duration_override_fails_before_approval_or_keys(self):
        from unittest.mock import Mock
        prompt=Mock(side_effect=AssertionError('must validate before approval'))
        for seconds in (0,-1,True,1.0,1801):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(BotError,'INVALID_RUN_DURATION'):
                run(self.path,self.root/'invalid-duration',seconds=seconds,read=prompt)
        prompt.assert_not_called()
        self.assertFalse((self.root/'invalid-duration').exists())
        self.assertEqual(self.http,[])

    def test_real_io_constructors_are_exercised_with_memory_transports_only(self):
        """Synthetic human permit; real SDK classes, zero real HTTP/WSS/key access."""
        # Use the actual approved two-hour request, not a short --seconds override:
        # otherwise a hidden one-hour Gateway cap is never exercised.
        value=json.loads(self.path.read_text());value['limits']['seconds']=7200
        self.path.write_text(json.dumps(value))
        import re
        from apps.ai_backend.credentials import CredentialStore
        from apps.ai_service.runtime.assistant import assistant_profile
        from apps.qq_bot.demo_runtime import qq_client
        from apps.qq_bot import management_cli,management_run
        base_async=httpx.AsyncClient;base_sync=httpx.Client
        model_calls=[];ws_options=[]
        async def model(request):
            body=json.loads(request.content);model_calls.append(body)
            answer=json.dumps(dict(contract='qq-hybrid-reply@2',kind='general',text='溶解氧是水中溶解的氧气。'))
            return httpx.Response(200,json={'id':'fake','object':'chat.completion','created':0,'model':body['model'],
                'choices':[{'index':0,'message':{'role':'assistant','content':answer},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})
        def qq(request):
            if request.url.path=='/app/getAppAccessToken':return httpx.Response(200,json={'access_token':'fictional','expires_in':3600})
            if request.url.path=='/gateway':return httpx.Response(200,json={'url':'wss://api.bot.qq.com/websocket/'})
            return httpx.Response(200,json={'id':'fake-accepted'})
        class MemoryAsync(base_async):
            def __init__(self,*args,**kwargs):super().__init__(*args,transport=httpx.MockTransport(model),**kwargs)
        class MemorySync(base_sync):
            def __init__(self,*args,**kwargs):super().__init__(*args,transport=httpx.MockTransport(qq),**kwargs)
        ref=assistant_profile('dashscope-qwen38-flash-r1').credential_ref
        def memory_store(*_a,**_k):return CredentialStore(process_env={ref:'fictional',management_cli.SECRET_REF:'fictional'})
        def websocket(url,**kwargs):
            ws_options.append((url,kwargs));return FakeSocket('123456789','group-a','member-a')
        with (patch.object(httpx,'AsyncClient',MemoryAsync),patch.object(httpx,'Client',MemorySync),
              patch.object(management_cli,'CredentialStore',memory_store),patch.object(management_run,'CredentialStore',memory_store),
              patch('websockets.sync.client.connect',side_effect=websocket)):
            code=run(self.path,self.root/'real-types-mocked',
                stop_requested=lambda:(self.root/'real-types-mocked/turn-1.result.json').exists(),
                read=lambda prompt:'APPROVE MANAGEMENT '+re.search(r'APPROVE MANAGEMENT ([a-f0-9]+)',prompt).group(1),
                emit_status=lambda *_a,**_k:None)
        self.assertEqual(code,0);self.assertEqual(len(model_calls),1)
        self.assertEqual(ws_options[0][0],'wss://api.bot.qq.com/websocket/')
        self.assertIsNone(ws_options[0][1]['proxy']);self.assertNotEqual(ws_options[0][1].get('ssl'),False)
        report=json.loads((self.root/'real-types-mocked/result.json').read_text())
        self.assertEqual(report['turns'][0]['sdk_resources']['state'],'CLOSED')
        self.assertEqual(report['turns'][0]['outcome']['history_code'],'HISTORY_COMMITTED')
