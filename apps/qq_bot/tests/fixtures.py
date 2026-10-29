from contextlib import ExitStack
from dataclasses import asdict,replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import asyncio,hashlib,json,threading,time,unittest
from unittest.mock import Mock,patch
import httpx
from openai import AsyncOpenAI
from apps.ai_backend.model_gateway import ModelResponse,ModelToolCall,GatewayError
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.sdk_resources import SDK_RESOURCES
from apps.ai_backend.tests import test_execution as sdk_fixture
from apps.ai_service.channel import OfflineChannelProvider,ChannelBudget
from apps.ai_service.service import ManagementAssistantService
from apps.ai_service.business_tools.current_water_quality import CURRENT_WATER_QUALITY as WATER
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from apps.qq_bot.ai_coordinator import QQAICoordinator
from apps.qq_bot.ai_delivery import OfflineQQGateway
from apps.qq_bot.ai_routing import OfflineQQAIRouter,OfflineGatewayAPI
from apps.qq_bot.ai_scheduler import QQAIJobScheduler
from apps.qq_bot.ai_configuration import QQAIConfig,QQAIGrant,load_ai_config
from apps.qq_bot.contracts import BotConfig,GroupAccess,BotError
from apps.qq_bot.monitoring_source import InstanceMonitoring,MonitoringSourceConfig
from apps.qq_bot.adapter import QQAdapter
from apps.qq_bot.run_consent import RunLimits
from apps.qq_bot.session_run import SessionRun
from apps.qq_bot.service import ReadOnlyQueries
from apps.qq_bot.gateway import QQGateway
from apps.qq_bot.trial_configuration import TrialInputs,write_new,read_json
APP='123456789'
def scripted():return OfflineChannelProvider((ModelResponse('offline',finish_reason='stop'),))
class QQFixture:

    def setUp(self):
        guards = ExitStack()
        self.addCleanup(guards.close)
        for target in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.socket.sendto', 'socket.getaddrinfo'):
            guards.enter_context(patch(target, side_effect=AssertionError('no external network')))
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.instance = self.root / 'instance'
        self.instance.mkdir()
        self.path = self.instance / 'monitoring.sqlite3'
        self.writer = MonitoringRepository(self.path)
        self.now = datetime(2026, 10, 25, tzinfo=timezone.utc)
        self.producer = MonitoringService(self.writer, device_names={'sim-pond-1': 'A', 'sim-pond-2': 'B'}, clock=lambda: self.now)
        self.sim = Simulator(start=self.now, device_id='sim-pond-1', session_id='qq-ai-offline')
        self.ingest()
        self.source = InstanceMonitoring(MonitoringSourceConfig('test-instance', self.instance, ('sim-pond-1', 'sim-pond-2')), clock=lambda: self.now)
        self.access = BotConfig(APP, (GroupAccess('group-a', 'sim-pond-1', ('member-a',), ('current',)), GroupAccess('group-b', 'sim-pond-2', ('member-b',), ('current',))))
        self.config = QQAIConfig(True, grants=(QQAIGrant('group-a', ('member-a',), 'sim-pond-1'), QQAIGrant('group-b', ('member-b',), 'sim-pond-2')))
        self.credentials = Mock()
        self.credentials.resolve.side_effect = AssertionError('never read real keys')
        self.provider = scripted()
        self.backend = ManagementAssistantService.monitoring_only(self.source, credentials=self.credentials, traces=JsonlTraceSink(self.root / 'trace.jsonl', tool_names=(WATER,)), policy_directory=self.root / 'policies', offline_channel_provider=self.provider, gateway_factory=Mock(side_effect=AssertionError('never construct real Provider')))
        self.coordinator = self.make()
        self.seq = 0

    def make(self, config=None):
        return QQAICoordinator(self.access, self.source, self.backend, config=config or self.config, clock=lambda: self.now)

    def ingest(self, quality='valid', *, oxygen=2.2):
        b = self.sim.advance()
        self.now = datetime.fromisoformat(b['timestamp'])
        b['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=oxygen, min=oxygen, max=oxygen, latest=oxygen)
        if quality == 'missing':
            b['water']['metrics']['ph'].update(mean=None, min=None, max=None, latest=None, valid_samples=0, invalid_samples=0)
        if quality == 'invalid':
            for m in b['water']['metrics'].values():
                m.update(mean=None, min=None, max=None, latest=None, valid_samples=0, invalid_samples=b['water']['sample_count'])
        self.producer.ingest(b)

    def packet(self, text='/问AI 当前水质如何？', *, group='group-a', member='member-a'):
        self.seq += 1
        return json.dumps(dict(op=0, t='GROUP_AT_MESSAGE_CREATE', s=self.seq, d=dict(id='ai-message-' + str(self.seq), group_openid=group, author=dict(member_openid=member, bot=False), timestamp=self.now.isoformat(), content=text))).encode()
fixture=SimpleNamespace(QQAIServiceTests=QQFixture,APP=APP)
class SessionRunTests:
    packet = fixture.QQAIServiceTests.packet
    ingest = fixture.QQAIServiceTests.ingest
    make = fixture.QQAIServiceTests.make

    def setUp(self):
        fixture.QQAIServiceTests.setUp(self)
        sdk_fixture.ExecutionTests.setUp(self)
        self.http = []
        self.mode = 'normal'
        self.started = threading.Event()
        self.members = ('member-a', 'member-b', 'member-c', 'member-d')
        self.access = replace(self.access, groups=(replace(self.access.groups[0], members=self.members), self.access.groups[1]))
        self.config = replace(self.config, grants=(replace(self.config.grants[0], members=self.members), self.config.grants[1]))
        for name, value in (('access.json', {'schema_version': 1, 'app_id': APP, 'groups': [asdict(g) for g in self.access.groups]}), ('ai.json', {'schema_version': 1, **asdict(self.config)}), ('source.json', {'schema_version': 1, 'instance_id': 'test-instance', 'data_root': str(self.instance), 'devices': ['sim-pond-1', 'sim-pond-2']})):
            write_new(self.root / name, value)
        self.inputs = TrialInputs.parse(dict(access_file=str(self.root / 'access.json'), ai_config=str(self.root / 'ai.json'), monitoring_config=str(self.root / 'source.json'), policy_directory=str(self.root / 'policies'), group_id='group-a', member_id='member-a'))

    def receive(self, text='现在水质怎么样？', **kwargs):
        self.gateway._dispatch_authenticated(json.loads(self.packet(text=text, **kwargs)))
        raw, _, proof = self.gateway._queue.get_nowait()
        self.gateway._queue.task_done()
        return self.router.receive(raw, transport_app_id=APP, mention=proof)

    def ask(self, text='现在水质怎么样？', **kwargs):
        code, task = self.receive(text, **kwargs)
        self.assertEqual(code, 'AI_ADMITTED')
        return self.scheduler.wait(task, 95)

    def test_ledger_write_failure_blocks_model_and_future_admissions(self):
        self.compose()
        with patch.object(self.host.ledger, '_append', side_effect=OSError('synthetic')):
            self.assertEqual(self.receive()[0], 'RUN_LEDGER_FAILED')
        self.assertEqual(self.receive()[0], 'RUN_LEDGER_FAILED')
        self.assertEqual(self.http, [])

    def test_delivery_checkpoint_failure_preserves_acceptance_and_halts(self):
        self.compose()
        with patch('apps.qq_bot.session_run.write_new', side_effect=OSError('synthetic')):
            done = self.ask()
        self.assertTrue(done['api_accepted'])
        self.assertIn('report_error', done)
        self.assertEqual(self.host.store.counts()['turns'], 0)
        self.assertEqual(self.receive()[0], 'RUN_CHECKPOINT_FAILED')
        self.assertEqual(len(self.delivery.posts), 1)

    def test_sdk_resource_fault_stops_run_and_new_request(self):
        self.compose()
        original = self.coordinator.execute

        class Broken:
            failure = 'SDK_CLEANUP_FAILED'

            def snapshot(self):
                return dict(state='QUARANTINED', cleanup_error=self.failure, thread_exited=False, local_io_closed=False)

        def broken(plan):
            result = original(plan)
            plan.handle._sdk_resource = Broken()
            return result
        with patch.object(self.coordinator, 'execute', side_effect=broken):
            done = self.ask()
        self.assertEqual(done['state'], 'FAILED')
        self.assertEqual(done['code'], 'SDK_CLEANUP_FAILED')
        self.assertEqual(self.host.ledger.report()['state'], 'HALTED')
        self.assertEqual(self.delivery.posts.__len__(), 0)

    def test_gateway_disconnect_cancel_and_reconnect_new_message_only(self):
        self.compose()
        self.mode = 'blocked'
        _, task = self.receive()
        self.assertTrue(self.started.wait(3))
        self.router.disconnected()
        done = self.scheduler.wait(task, 8)
        self.assertEqual(done['state'], 'CANCELLED')
        self.assertEqual(self.host.store.counts()['turns'], 0)
        self.mode = 'normal'
        self.router.connected()
        self.assertEqual(self.ask()['state'], 'DELIVERED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'], 2)

    def test_total_timeout_closed_resources_allows_next_independent_message(self):
        self.compose()
        self.mode = 'blocked'
        _, task = self.receive()
        self.assertTrue(self.started.wait(3))
        self.scheduler.cancel(task, reason='AI_TOTAL_TIMEOUT')
        done = self.scheduler.wait(task, 8)
        self.assertEqual(done['state'], 'EXPIRED')
        self.assertEqual(self.host.turns[0]['sdk_resources']['state'], 'CLOSED')
        self.mode = 'normal'
        self.assertEqual(self.ask()['state'], 'DELIVERED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'], 2)

    def test_queued_expiry_consumes_and_does_not_start_sdk(self):
        self.compose(members=self.members)
        self.mode = 'blocked'
        _, first = self.receive()
        self.assertTrue(self.started.wait(3))
        _, queued = self.receive(member='member-b')
        with self.scheduler._cv:
            self.scheduler._jobs[queued].queue_deadline = time.monotonic() - 1
        done = self.scheduler.wait(queued, 8)
        self.assertEqual(done['state'], 'EXPIRED')
        self.assertEqual(len(self.http), 1)
        self.assertEqual(self.host.sessions[1].requests, 0)
        self.assertEqual(self.host.ledger.report()['consumed_turns'], 2)

    def test_owner_loss_halts_and_cancels_without_new_model(self):
        self.compose()
        self.mode = 'blocked'
        _, task = self.receive()
        self.assertTrue(self.started.wait(3))
        with patch.object(self.host.ledger._owner, 'check', side_effect=BotError('RUN_OWNER_LOST')):
            done = self.scheduler.wait(task, 8)
        self.assertIn(done['state'], ('CANCELLED', 'FAILED'))
        self.assertEqual(self.host.ledger.report()['stop_code'], 'RUN_OWNER_LOST')
        self.assertEqual(self.receive()[0], 'RUN_OWNER_LOST')
        self.assertEqual(len(self.http), 1)

    def test_expiry_cancels_without_any_new_message(self):
        self.compose()
        self.mode = 'blocked'
        _, task = self.receive()
        self.assertTrue(self.started.wait(3))
        self.now += timedelta(minutes=31)
        self.assertEqual(self.scheduler.wait(task, 8)['state'], 'CANCELLED')
        self.assertEqual(self.host.ledger.report()['stop_code'], 'RUN_EXPIRED')

    def test_stop_closes_resources_writes_final_report_clears_ram(self):
        self.compose()
        self.ask()
        report = self.host.stop(self.scheduler)
        self.assertTrue(report['ram_cleared'])
        self.assertTrue((self.host.directory / 'result.json').is_file())
        self.assertTrue(all((not t.is_alive() for t in self.scheduler._threads)))
        self.assertTrue(all((s.report()['sdk_resources']['state'] == 'CLOSED' for s in self.host.sessions)))
