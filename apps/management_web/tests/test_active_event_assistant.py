"""Exercise the opt-in event Tool through the normal Web entry points."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.tests.support import FakeSDK, final_chunks, sdk_final, sdk_tool, tool_chunks
from apps.ai_backend.tests import test_execution as offline_guard
from apps.ai_service.active_event_execution import ActiveEventTrialConfig, ACTIVE_EVENT_TOOL_NAMES
from apps.ai_service.business_tools.active_events import ACTIVE_EVENTS
from apps.ai_service.business_tools.current_water_quality import CURRENT_WATER_QUALITY
from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.service import ManagementAssistantService
from apps.knowledge.tests.support import reference_knowledge
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator


class ActiveEventAssistantTests(unittest.TestCase):
    def setUp(self):
        offline_guard.ExecutionTests.setUp(self)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        now = datetime(2026, 11, 9, 10, tzinfo=timezone.utc)
        self.monitoring = MonitoringService(MonitoringRepository(self.root / 'monitoring.sqlite3'),
            device_names={'pond-a': 'Test pond A', 'pond-b': 'Test pond B'}, clock=lambda: now)
        simulator = Simulator(device_id='pond-a', scenario='low_oxygen',
            start=now - timedelta(seconds=30), session_id='event-tool-web')
        for _ in range(3):
            batch = simulator.advance()
            batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2, min=2.2, max=2.2, latest=2.2)
            self.monitoring.ingest(batch)
        self.profile = assistant_profile('dashscope-qwen38-flash-r1')

    def configure(self, responses, *, enabled=True, selection=(CURRENT_WATER_QUALITY, ACTIVE_EVENTS)):
        self.sdk = FakeSDK(responses, model=self.profile.model)
        self.backend = ManagementAssistantService(self.monitoring, knowledge=reference_knowledge(),
            credentials=CredentialStore(process_env={self.profile.credential_ref: 'synthetic-event-test-key'}),
            traces=JsonlTraceSink(self.root / 'trace.jsonl', tool_names=ACTIVE_EVENT_TOOL_NAMES),
            policy_directory=self.root / 'policy', active_event_config=ActiveEventTrialConfig(enabled=enabled),
            gateway_factory=lambda: OpenAICompatibleAdapter(async_client_factory=self.sdk.factory))
        web = ManagementAssistant(self.backend)
        self.client = create_app(data_service=self.monitoring, ai=web).test_client()
        self.headers = {'X-Management-AI': web.browser_token}
        policy = self.client.get('/api/ai/tool-policy').get_json()
        saved = self.client.post('/api/ai/tool-policy', headers=self.headers,
            json=dict(epoch=policy['epoch'], revision=policy['revision'], selected_tools=selection))
        self.assertEqual(saved.status_code, 200)

    def body(self, *, device='pond-a', streaming=False, confirm=True, question='现在有什么异常？'):
        config = self.client.get('/api/ai/bootstrap?device=' + device).get_json()
        execution = config['presets'][0]['streaming' if streaming else 'execution']
        control = self.client.post('/api/ai/requests', headers=self.headers,
            json={'epoch': config['epoch']}).get_json()
        return dict(preset_id=self.profile.preset_id, device_id=device, question=question, history=[],
                    epoch=config['epoch'], revision=execution['revision'], confirm_network=confirm, **control)

    def test_normal_and_streaming_commit_grounded_event_and_hide_uncommitted_preview(self):
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                self.configure([tool_chunks(ACTIVE_EVENTS, 'event-1', '{}'), final_chunks('Event summary.')]
                               if streaming else [sdk_tool(ACTIVE_EVENTS, 'event-1', '{}', self.profile.model),
                               sdk_final('Event summary.', model=self.profile.model)])
                response = self.client.post('/api/ai/messages' + ('/stream' if streaming else ''),
                    headers=self.headers, json=self.body(streaming=streaming))
                self.assertEqual(response.status_code, 200)
                if streaming:
                    events = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines()
                              if line.startswith('data: ')]
                    self.assertNotIn('preview', [event['kind'] for event in events])
                    result = events[-1]['result']
                else:
                    result = response.get_json()['result']
                response.close()
                self.assertTrue(result['successful_turn'], result.get('error_code'))
                self.assertEqual(len(self.sdk.bodies), 2)
                message = next(item for item in self.sdk.bodies[1]['messages'] if item['role'] == 'tool')
                payload = json.loads(message['content'])
                self.assertTrue(any(event['code'].startswith('OXYGEN_') for event in payload['items']))
                self.assertTrue(all(client.closed for client in self.sdk.clients))

    def test_explicit_event_question_requires_receipt_and_network_confirmation(self):
        questions = ('现在有什么异常？', '现在鱼塘有什么异常？', '帮我看看现在有哪些告警？',
                     '目前有哪些事件还没有结束？', '当前还在发生的事件')
        self.configure([sdk_final('Unverified event claim.', model=self.profile.model) for _ in questions])
        response = self.client.post('/api/ai/messages', headers=self.headers, json=self.body(confirm=False))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.sdk.bodies, [])
        for question in questions:
            with self.subTest(question=question):
                response = self.client.post('/api/ai/messages', headers=self.headers, json=self.body(question=question))
                result = response.get_json()['result']
                self.assertEqual(result['error_code'], 'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
                self.assertEqual(result['final_text'], '')

    def test_combines_event_and_water_within_existing_budget(self):
        self.configure([sdk_tool(CURRENT_WATER_QUALITY, 'water-1', '{}', self.profile.model),
            sdk_tool(ACTIVE_EVENTS, 'event-1', '{}', self.profile.model),
            sdk_final('Two sources checked.', model=self.profile.model)])
        response = self.client.post('/api/ai/messages', headers=self.headers,
            json=self.body(question='What is the dissolved oxygen and what events are active?'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['result']['successful_turn'])
        self.assertEqual(len(self.sdk.bodies), 3)
        self.assertEqual(len([item for item in self.sdk.bodies[-1]['messages'] if item['role']=='tool']), 2)
        self.assertTrue(all(client.closed for client in self.sdk.clients))

    def test_launcher_only_opt_ins_event_tool_for_web(self):
        from scripts.dev.local_session import commands
        web, simulator = commands('python', 'normal', 8766, 42, event_trial=True)
        self.assertIn('--assistant-event-trial', web)
        self.assertNotIn('--assistant-event-trial', simulator)
        for flags in ({'streaming': False}, {'multi_round': False}):
            with self.assertRaisesRegex(RuntimeError, 'EVENT_TRIAL_REQUIRES_NORMAL_AND_STREAMING'):
                commands('python', 'normal', 8766, 42, event_trial=True, **flags)

    def test_startup_and_policy_both_control_exposure(self):
        for enabled, selection in [(False, (CURRENT_WATER_QUALITY, ACTIVE_EVENTS)),
                                   (True, (CURRENT_WATER_QUALITY,))]:
            with self.subTest(enabled=enabled):
                self.configure([], enabled=enabled, selection=selection)
                config = self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
                self.assertNotIn(ACTIVE_EVENTS, config['tools'])
                self.assertEqual(self.sdk.bodies, [])
