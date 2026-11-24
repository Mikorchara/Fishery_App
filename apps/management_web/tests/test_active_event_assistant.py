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
from apps.ai_service.business_tools.fishery_knowledge import SEARCH_FISHERY_KNOWLEDGE
from apps.ai_service.business_tools.registry import RESULT_INSTRUCTIONS
from apps.ai_service.business_tools.water_quality_history import WATER_QUALITY_HISTORY
from apps.ai_service.execution import load_execution_config
from apps.ai_service.normal_selection import load_unified_tool_trials
from apps.ai_service.runtime.assistant import MULTI_ROUND_SYSTEM_INSTRUCTION, assistant_profile
from apps.ai_service.service import ManagementAssistantService
from apps.ai_service.streaming import load_streaming_config
from apps.knowledge.tests.support import reference_knowledge
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.monitoring.tests import test_device_events as board_fixtures
from apps.simulator.generator import Simulator


_EVENT_QUESTION = '现在有什么活动事件？'
_MIXED_QUESTION = '现在有什么活动事件？顺便查一下当前溶解氧是多少？'
_WATER_TOOLS = (CURRENT_WATER_QUALITY, SEARCH_FISHERY_KNOWLEDGE)
_NOT_ENABLED = '本次服务未启用当前事件查询，无法核实当前事件。'
_NOT_AUTHORIZED = '当前事件查询工具在本轮未获授权，无法核实当前事件。'
_UNSUPPORTED_MODE = '当前问答模式未提供当前事件查询，本轮无法核实当前事件。'
_UNSUPPORTED_REPLY = '当前没有任何活动事件，当前溶解氧为 99 mg/L。'


class ActiveEventAssistantTests(unittest.TestCase):
    def setUp(self):
        offline_guard.ExecutionTests.setUp(self)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = datetime(2026, 11, 9, 10, tzinfo=timezone.utc)
        self.monitoring = MonitoringService(MonitoringRepository(self.root / 'monitoring.sqlite3'),
            device_names={'pond-a': 'Test pond A', 'pond-b': 'Test pond B'}, clock=lambda: self.now)
        simulator = Simulator(device_id='pond-a', scenario='low_oxygen',
            start=self.now - timedelta(seconds=30), session_id='event-tool-web')
        for _ in range(3):
            batch = simulator.advance()
            batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2, min=2.2, max=2.2, latest=2.2)
            self.monitoring.ingest(batch)
        self.profile = assistant_profile('dashscope-qwen38-flash-r1')

    def configure(self, responses, *, enabled=True, selection=(CURRENT_WATER_QUALITY, ACTIVE_EVENTS),
                  multi_round=True, board_device_id=None):
        self.sdk = FakeSDK(responses, model=self.profile.model)
        self.backend = ManagementAssistantService(self.monitoring, knowledge=reference_knowledge(),
            credentials=CredentialStore(process_env={self.profile.credential_ref: 'synthetic-event-test-key'}),
            traces=JsonlTraceSink(self.root / 'trace.jsonl', tool_names=ACTIVE_EVENT_TOOL_NAMES),
            policy_directory=self.root / 'policy', active_event_config=ActiveEventTrialConfig(
                enabled=enabled, device_report_device_id=board_device_id),
            execution_config=load_execution_config(enable_trial=multi_round),
            streaming_config=load_streaming_config(enable_trial=True),
            unified_config=load_unified_tool_trials(normal=True, streaming=True),
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
        preset = next(row for row in config['presets'] if row['preset_id'] == self.profile.preset_id)
        execution = preset['streaming' if streaming else 'execution']
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
                first, second = self.sdk.bodies
                self.assertEqual(first['messages'][0]['content'], MULTI_ROUND_SYSTEM_INSTRUCTION)
                self.assertEqual(first['tools'], second['tools'])
                event_definition = next(item['function'] for item in first['tools']
                                        if item['function']['name'] == ACTIVE_EVENTS)
                self.assertTrue(event_definition['description'].startswith(
                    '问当前事件、异常或告警，且未限定为水质时，优先用本工具。'
                    '只问当前水质读数或告警时用获准的当前水质工具。'))
                self.assertEqual(event_definition['parameters']['properties'], {})
                self.assertEqual(second['messages'][0]['role'], 'system')
                self.assertTrue(second['messages'][0]['content'].startswith(MULTI_ROUND_SYSTEM_INSTRUCTION))
                self.assertIn(RESULT_INSTRUCTIONS[ACTIVE_EVENTS], second['messages'][0]['content'])
                self.assertNotIn(RESULT_INSTRUCTIONS[CURRENT_WATER_QUALITY], second['messages'][0]['content'])
                self.assertEqual(second['messages'][1], first['messages'][1])
                call = second['messages'][-2]['tool_calls'][0]
                message = second['messages'][-1]
                self.assertEqual(call['id'], message['tool_call_id'])
                self.assertEqual(message['role'], 'tool')
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
        first, second, third = [body['messages'][0]['content'] for body in self.sdk.bodies]
        self.assertEqual(first, MULTI_ROUND_SYSTEM_INSTRUCTION)
        self.assertNotIn(RESULT_INSTRUCTIONS[ACTIVE_EVENTS], second)
        self.assertEqual(second.count(RESULT_INSTRUCTIONS[CURRENT_WATER_QUALITY]), 1)
        self.assertEqual(third.count(RESULT_INSTRUCTIONS[CURRENT_WATER_QUALITY]), 1)
        self.assertEqual(third.count(RESULT_INSTRUCTIONS[ACTIVE_EVENTS]), 1)
        self.assertEqual(self.sdk.bodies[-1]['tool_choice'], 'none')
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

    def send_case(self, question, *, streaming, device='pond-a'):
        response = self.client.post('/api/ai/messages' + ('/stream' if streaming else ''),
            headers=self.headers, json=self.body(question=question, streaming=streaming, device=device))
        self.assertEqual(response.status_code, 200, response.get_json(silent=True))
        if streaming:
            rows = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines()
                    if line.startswith('data: ')]
            self.assertEqual(rows[-1]['kind'], 'final', rows[-1])
            result = rows[-1]['result']
        else:
            rows = []
            result = response.get_json()['result']
        response.close()
        self.assertTrue(result['successful_turn'], result)
        return result, rows

    def test_event_notice_distinguishes_disabled_from_unauthorized_in_normal_and_streaming(self):
        for streaming in (False, True):
            for enabled, selection, reason in (
                (False, (*_WATER_TOOLS, ACTIVE_EVENTS), _NOT_ENABLED),
                (True, _WATER_TOOLS, _NOT_AUTHORIZED),
            ):
                with self.subTest(streaming=streaming, enabled=enabled):
                    self.configure([final_chunks(_UNSUPPORTED_REPLY) if streaming else
                        sdk_final(_UNSUPPORTED_REPLY, model=self.profile.model)],
                        enabled=enabled, selection=selection)
                    result, rows = self.send_case(_EVENT_QUESTION, streaming=streaming)
                    self.assertEqual(result['activity']['counts']['tools_executed'], 0)
                    self.assertIn(reason, result['final_text'])
                    self.assertNotIn(_UNSUPPORTED_REPLY, result['final_text'])
                    self.assertFalse(any(row['kind'] == 'preview' for row in rows))
                    self.assertNotIn(_UNSUPPORTED_REPLY, json.dumps(rows, ensure_ascii=False))
                    body, = self.sdk.bodies
                    self.assertNotIn(ACTIVE_EVENTS, [item['function']['name'] for item in body['tools']])
                    system = body['messages'][0]['content']
                    self.assertIn(reason, system)
                    self.assertNotIn(CURRENT_WATER_QUALITY, system)

    def test_legacy_normal_mode_explains_event_capability_limit(self):
        self.profile = assistant_profile('ollama-qwen35-4b-r1')
        self.configure([sdk_final(_UNSUPPORTED_REPLY, model=self.profile.model)],
                       selection=(*_WATER_TOOLS, ACTIVE_EVENTS), multi_round=False)
        result, _ = self.send_case(_EVENT_QUESTION, streaming=False)
        self.assertIn(_UNSUPPORTED_MODE, result['final_text'])
        self.assertNotIn(_UNSUPPORTED_REPLY, result['final_text'])
        self.assertEqual(result['activity']['counts']['tools_executed'], 0)
        first, = self.sdk.bodies
        self.assertIn(_UNSUPPORTED_MODE, first['messages'][0]['content'])
        self.assertNotIn(ACTIVE_EVENTS, [item['function']['name'] for item in first['tools']])

    def test_mixed_event_notice_uses_only_the_current_water_receipt(self):
        for streaming in (False, True):
            for device, water_authorized, read_water in (
                ('pond-a', True, True),
                ('pond-b', True, True),
                ('pond-a', True, False),
                ('pond-a', False, False),
            ):
                with self.subTest(streaming=streaming, device=device,
                                  water_authorized=water_authorized, read_water=read_water):
                    if streaming:
                        plans = [tool_chunks(CURRENT_WATER_QUALITY)] if read_water else []
                        plans.append(final_chunks(_UNSUPPORTED_REPLY))
                    else:
                        plans = [sdk_tool(CURRENT_WATER_QUALITY, model=self.profile.model)] if read_water else []
                        plans.append(sdk_final(_UNSUPPORTED_REPLY, model=self.profile.model))
                    self.configure(plans, selection=_WATER_TOOLS if water_authorized else (SEARCH_FISHERY_KNOWLEDGE,))
                    result, rows = self.send_case(_MIXED_QUESTION, streaming=streaming, device=device)
                    reply = result['final_text']
                    self.assertIn(_NOT_AUTHORIZED, reply)
                    self.assertNotIn('99 mg/L', reply)
                    self.assertNotIn('没有任何活动事件', reply)
                    self.assertFalse(any(row['kind'] == 'preview' for row in rows))
                    self.assertNotIn(_UNSUPPORTED_REPLY, json.dumps(rows, ensure_ascii=False))
                    self.assertEqual(result['activity']['counts']['tools_executed'], int(read_water))
                    self.assertEqual(len(self.sdk.bodies), 1 + int(read_water))
                    first = self.sdk.bodies[0]
                    names = [item['function']['name'] for item in first['tools']]
                    self.assertNotIn(ACTIVE_EVENTS, names)
                    self.assertEqual(CURRENT_WATER_QUALITY in names, water_authorized)
                    self.assertEqual(CURRENT_WATER_QUALITY in first['messages'][0]['content'], water_authorized)
                    if read_water:
                        final = self.sdk.bodies[-1]
                        payload, = [json.loads(item['content']) for item in final['messages']
                                    if item['role'] == 'tool']
                        self.assertIn('未获授权', final['messages'][0]['content'])
                        self.assertEqual(payload['device_id'], device)
                        self.assertEqual(payload['status'], 'OK' if device == 'pond-a' else 'NO_DATA')
                    if read_water and device == 'pond-a':
                        water = payload['water_quality']
                        value = water['dissolved_oxygen_mg_l']
                        observed = datetime.fromisoformat(water['observed_at']).astimezone(timezone(timedelta(hours=8)))
                        for phrase in ('模拟水质', device, f'北京时间 {observed:%Y-%m-%d %H:%M:%S}', f'{value:g} mg/L'):
                            self.assertIn(phrase, reply)
                    else:
                        self.assertNotIn('mg/L', reply)
                        if not water_authorized:
                            self.assertIn('未获授权', reply.partition(_NOT_AUTHORIZED)[2])
                        else:
                            self.assertRegex(reply, '未取得|暂无|缺少|无法核实.+溶解氧')

    def test_water_only_with_events_unauthorized_gets_no_notice(self):
        self.configure([sdk_tool(CURRENT_WATER_QUALITY, model=self.profile.model),
                        sdk_final('本轮模拟水质的溶解氧触发了水质告警。', model=self.profile.model)],
                       selection=_WATER_TOOLS)
        result, _ = self.send_case('帮我看看目前的水质有哪些告警。', streaming=False)
        first, final = self.sdk.bodies
        instruction = first['messages'][0]['content']
        self.assertTrue(instruction.startswith(MULTI_ROUND_SYSTEM_INSTRUCTION))
        self.assertIn('本轮只问当前水质告警', instruction)
        self.assertNotIn('未获授权', instruction)
        self.assertIn(RESULT_INSTRUCTIONS[CURRENT_WATER_QUALITY], final['messages'][0]['content'])
        self.assertNotIn('未获授权', result['final_text'])
        self.assertEqual(result['activity']['counts']['tools_executed'], 1)

    def test_authorized_event_empty_results_keep_their_real_receipts(self):
        for status, conclusion in (
            ('NO_DATA', '无法核实'),
            ('NO_MATCH', '未查到'),
        ):
            with self.subTest(status=status):
                if status == 'NO_MATCH':
                    simulator = Simulator(device_id='pond-b', scenario='normal',
                        start=self.monitoring.clock() - timedelta(seconds=10), session_id='event-no-match')
                    self.monitoring.ingest(simulator.advance())
                self.configure([sdk_tool(ACTIVE_EVENTS, model=self.profile.model),
                                sdk_final(_UNSUPPORTED_REPLY, model=self.profile.model)])
                result, _ = self.send_case(_EVENT_QUESTION, streaming=False, device='pond-b')
                first, final = self.sdk.bodies
                self.assertEqual(first['messages'][0]['content'], MULTI_ROUND_SYSTEM_INSTRUCTION)
                payload, = [json.loads(item['content']) for item in final['messages'] if item['role'] == 'tool']
                self.assertEqual(payload['status'], status)
                self.assertEqual(result['activity']['counts']['tools_executed'], 1)
                self.assertIn(conclusion, result['final_text'])
                self.assertNotIn(_UNSUPPORTED_REPLY, result['final_text'])

    def test_empty_scope_replies_keep_assessed_water_separate_from_missing_or_stale_board(self):
        for board_state, streaming in (('MISSING', False), ('MISSING', True), ('STALE', False), ('STALE', True)):
            with self.subTest(board_state=board_state, streaming=streaming):
                if board_state == 'STALE' and not streaming:
                    report = board_fixtures.DeviceEventTests.report(self, positive=False)
                    accepted = self.monitoring.repository.import_device_report(report,
                        received_at=self.now, inbox_cursor=1, now=self.now)
                    self.assertEqual(accepted['status'], 'no_signal')
                    self.now += timedelta(seconds=121)
                if not streaming:
                    simulator = Simulator(device_id='pond-b', mode='water-only',
                        start=self.now - timedelta(seconds=10), session_id=f'water-{board_state}')
                    self.monitoring.ingest(simulator.advance())
                wrong_answer = '当前没有任何异常，所有设备都正常。'
                plans = ([tool_chunks(ACTIVE_EVENTS), final_chunks(wrong_answer)] if streaming else
                    [sdk_tool(ACTIVE_EVENTS, model=self.profile.model), sdk_final(wrong_answer, model=self.profile.model)])
                self.configure(plans, board_device_id='board-1')
                result, rows = self.send_case(_EVENT_QUESTION, streaming=streaming, device='pond-b')
                first, final = self.sdk.bodies
                self.assertNotIn('observation_scope', first['messages'][0]['content'])
                guidance = final['messages'][0]['content']
                self.assertIn('observation_scope', guidance)
                self.assertIn('ASSESSED', guidance)
                payload = json.loads(final['messages'][-1]['content'])
                self.assertEqual(payload['projection_version'], 'management-active-events@3')
                self.assertTrue(payload['evaluated_at'].endswith('+08:00'))
                self.assertEqual(payload['status'], 'NO_MATCH')
                self.assertEqual(payload['items'], [])
                scope = [(row['source_kind'], row['device_id'], row['channel'], row['state'])
                         for row in payload['observation_scope']]
                self.assertEqual(scope, [('simulator', 'pond-b', 'water', 'ASSESSED'),
                    ('simulator', 'pond-b', 'visual', 'MISSING'), ('device_report', 'board-1', 'visual', board_state)])
                self.assertEqual([row['observed_at'] for row in payload['observation_scope']],
                    [observation['observed_at'] for source in payload['sources'] for observation in source['observations']])
                reply = result['final_text']
                self.assertIn('模拟水质', reply)
                self.assertIn('未查到', reply)
                self.assertIn('板端视觉', reply)
                self.assertIn('board-1', reply)
                self.assertIn('外观', reply)
                self.assertIn('行为', reply)
                self.assertIn('缺少观测' if board_state == 'MISSING' else '已过期', reply)
                self.assertNotIn('所有设备都正常', reply)
                self.assertNotIn('所有设备都正常', json.dumps(rows, ensure_ascii=False))
                self.assertFalse(any(row['kind'] == 'preview' for row in rows))

    def test_positive_simulator_event_and_limited_board_remain_distinct_in_published_reply(self):
        wrong = '模拟水质有严重低氧事件。板端未查到匹配事件。'
        for board_state, streaming in (('MISSING', False), ('MISSING', True), ('STALE', False), ('STALE', True)):
            with self.subTest(board_state=board_state, streaming=streaming):
                if board_state == 'STALE' and not streaming:
                    report = board_fixtures.DeviceEventTests.report(self, positive=False)
                    receipt = self.monitoring.repository.import_device_report(report,
                        received_at=self.now, inbox_cursor=1, now=self.now)
                    self.assertEqual(receipt['status'], 'no_signal')
                    self.now += timedelta(seconds=121)
                    simulator = Simulator(device_id='pond-a', scenario='low_oxygen',
                        start=self.now - timedelta(seconds=30), session_id='event-board-stale-water')
                    for _ in range(3):
                        batch = simulator.advance()
                        batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2, min=2.2, max=2.2, latest=2.2)
                        self.monitoring.ingest(batch)
                plans = ([tool_chunks(ACTIVE_EVENTS), final_chunks(wrong)] if streaming else
                    [sdk_tool(ACTIVE_EVENTS, model=self.profile.model), sdk_final(wrong, model=self.profile.model)])
                self.configure(plans, board_device_id='board-1')
                result, rows = self.send_case(_EVENT_QUESTION, streaming=streaming)
                payload = json.loads(self.sdk.bodies[-1]['messages'][-1]['content'])
                self.assertEqual(payload['status'], 'OK')
                risk = next(row for row in payload['items']
                            if row['code'].startswith('OXYGEN_') and row['source_kind'] == 'simulator')
                board_scope, = [row for row in payload['observation_scope'] if row['source_kind'] == 'device_report']
                self.assertEqual((board_scope['device_id'], board_scope['channel'], board_scope['state']),
                                 ('board-1', 'visual', board_state))
                reply = result['final_text']
                self.assertIn(f"在模拟设备 pond-a的记录中查到{risk['title']}（活动）", reply)
                limit = '缺少观测' if board_state == 'MISSING' else '观测已过期'
                self.assertIn(f'设备报告 board-1的视觉{limit}，暂时无法核实外观和行为异常', reply)
                self.assertNotIn('板端未查到匹配事件', reply)
                self.assertFalse(any(row['kind'] == 'preview' for row in rows))

    def test_explicit_mixed_empty_event_and_reading_uses_both_receipts(self):
        question = '先查现在有哪些活动事件，再告诉我当前的溶解氧读数。'
        simulator = Simulator(device_id='pond-b', mode='water-only',
            start=self.now - timedelta(seconds=10), session_id='mixed-scope-water')
        self.monitoring.ingest(simulator.advance())
        wrong = '当前没有活动事件，溶解氧为 99 mg/L。'
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                plans = [tool_chunks(ACTIVE_EVENTS, 'events'), tool_chunks(CURRENT_WATER_QUALITY, 'water'),
                    final_chunks(wrong)] if streaming else [
                    sdk_tool(ACTIVE_EVENTS, 'events', model=self.profile.model),
                    sdk_tool(CURRENT_WATER_QUALITY, 'water', model=self.profile.model),
                    sdk_final(wrong, model=self.profile.model)]
                self.configure(plans, board_device_id='board-1')
                result, rows = self.send_case(question, streaming=streaming, device='pond-b')
                event, water = [json.loads(m['content']) for m in self.sdk.bodies[-1]['messages'] if m['role'] == 'tool']
                self.assertEqual(event['status'], 'NO_MATCH')
                reading = water['water_quality']
                at = datetime.fromisoformat(reading['observed_at']).astimezone(timezone(timedelta(hours=8)))
                self.assertIn(f"{reading['dissolved_oxygen_mg_l']} mg/L", result['final_text'])
                self.assertIn(f'北京时间 {at:%Y-%m-%d %H:%M:%S}', result['final_text'])
                self.assertIn('的有效观测范围内未查到匹配事件', result['final_text'])
                self.assertIn('板端视觉（board-1）缺少观测', result['final_text'])
                self.assertNotIn(wrong, result['final_text'])
                self.assertFalse(any(row['kind'] == 'preview' for row in rows))

        self.configure([sdk_tool(CURRENT_WATER_QUALITY, model=self.profile.model),
                        sdk_final(wrong, model=self.profile.model)], board_device_id='board-1')
        response = self.client.post('/api/ai/messages', headers=self.headers,
            json=self.body(question=question, device='pond-b'))
        result = response.get_json()['result']
        self.assertEqual(result['error_code'], 'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
        self.assertEqual(result['final_text'], '')

    def test_historical_summary_replaces_a_wrong_date_and_reports_real_gaps(self):
        self.now = datetime(2026, 11, 21, 16, 15, tzinfo=timezone.utc)
        simulator = Simulator(device_id='pond-b', mode='water-only',
            start=self.now - timedelta(minutes=2), session_id='cross-date')
        for _ in range(2):
            self.monitoring.ingest(simulator.advance(60))
        arguments = '{"lookback_minutes":30,"metrics":["dissolved_oxygen_mg_l"]}'
        wrong = '北京时间 2026-11-21 15:45 至 16:15 全程可靠，记录了 99 mg/L。'
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                plans = [tool_chunks(WATER_QUALITY_HISTORY, 'history', arguments), final_chunks(wrong)] if streaming else [
                    sdk_tool(WATER_QUALITY_HISTORY, 'history', arguments, self.profile.model),
                    sdk_final(wrong, model=self.profile.model)]
                self.configure(plans, enabled=False, selection=(CURRENT_WATER_QUALITY, WATER_QUALITY_HISTORY))
                result, rows = self.send_case('最近30分钟溶解氧有什么变化？', streaming=streaming, device='pond-b')
                for request in self.sdk.bodies:
                    system = request['messages'][0]['content']
                    self.assertIn('lookback_minutes=30', system)
                    self.assertIn('metrics=["dissolved_oxygen_mg_l"]', system)
                    self.assertIn('勿调用当前水质或其他工具补齐', system)
                body = result['final_text']
                self.assertIn('北京时间 2026-11-21 23:45:00 至 2026-11-22 00:15:00', body)
                self.assertIn('共 2 个可靠窗口，覆盖 6.7%', body)
                self.assertIn('缺少可靠观测的时段包括2026-11-21 23:45:00 至 2026-11-22 00:13:00', body)
                self.assertNotIn('99 mg/L', body)
                self.assertFalse(any(row['kind'] == 'preview' for row in rows))

    def test_historical_summary_rejects_a_receipt_for_another_period(self):
        self.configure([sdk_tool(WATER_QUALITY_HISTORY, arguments='{"lookback_minutes":10}', model=self.profile.model),
            sdk_final('错误范围。', model=self.profile.model)], enabled=False,
            selection=(CURRENT_WATER_QUALITY, WATER_QUALITY_HISTORY))
        response = self.client.post('/api/ai/messages', headers=self.headers,
            json=self.body(question='过去半小时的溶解氧最低值是什么时候？', device='pond-b'))
        result = response.get_json()['result']
        self.assertEqual(result['error_code'], 'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
        self.assertEqual(result['final_text'], '')

    def test_behavior_followup_publishes_board_limit_from_the_actual_receipt(self):
        question = '有几个视频被模型标为异常？行为结果是什么时候生成的，能知道上报时间吗？'
        wrong = '该设备没有异常视频，刚刚已成功上报。'
        self.configure([tool_chunks(ACTIVE_EVENTS), final_chunks(wrong)], board_device_id='board-1')
        result, rows = self.send_case(question, streaming=True)
        self.assertIn('get_active_events', self.sdk.bodies[0]['messages'][0]['content'])
        self.assertIn('未取得设备报告 board-1 中可核实的行为模型结果', result['final_text'])
        self.assertIn('本轮结果未提供行为上报时间', result['final_text'])
        self.assertNotIn(wrong, result['final_text'])
        self.assertFalse(any(row['kind'] == 'preview' for row in rows))
