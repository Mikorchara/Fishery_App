"""Event and history scope acceptance through the existing read-only Web runtime."""

from datetime import timedelta
import json
from types import SimpleNamespace
import unittest

from apps.ai_backend.tests.support import final_chunks, sdk_final, sdk_tool, tool_chunks
from apps.ai_backend.tools.policy import ToolPolicy
from apps.ai_service.business_tools.active_events import ACTIVE_EVENTS
from apps.ai_service.business_tools.water_quality_history import WATER_QUALITY_HISTORY
from apps.ai_service.runtime.event_history import event_history_for_turn, event_history_query
from apps.management_web.tests import test_active_event_assistant as web_fixtures
from apps.monitoring.tests.test_device_events import DeviceEventTests as BoardFixtures
from apps.simulator.generator import Simulator


QUESTION = '先查当前事件，再查过去30分钟的溶解氧。请分别说明结论，历史部分给出时段和可靠窗口总体均值。'
_BOTH = (ACTIVE_EVENTS, WATER_QUALITY_HISTORY)
_ARGUMENTS = '{"lookback_minutes":30,"metrics":["dissolved_oxygen_mg_l"]}'
_UNVERIFIED = '所有设备均正常，历史总体均值为 99 mg/L。'


class EventHistoryMatcherTests(unittest.TestCase):
    def test_exact_history_mean_question_and_safe_variants(self):
        for question, minutes in (
            (QUESTION, 30),
            ('当前有哪些事件？顺便查最近10分钟的溶解氧总体均值。', 10),
            ('请先查询当前活动事件，以及最近一小时的溶氧可靠窗口总体均值。', 60),
            ('查一下现在的事件，再查询过去半小时的溶解氧。历史部分请给出时间范围和总体均值。', 30),
        ):
            with self.subTest(question=question):
                match = event_history_query(question)
                self.assertIsNotNone(match)
                self.assertEqual((match.minutes, match.metric), (minutes, 'dissolved_oxygen_mg_l'))

    def test_excludes_followups_different_metrics_and_requests_requiring_other_sources(self):
        for question in (
            '先查当前事件，再查过去30分钟的溶解氧。',
            '先查当前事件，再查过去30分钟的水温总体均值。',
            '先查当前事件，再查过去20分钟的溶解氧总体均值。',
            '先查之前的事件，再查过去30分钟的溶解氧总体均值。',
            '先查当前事件，再查过去30分钟的溶解氧总体均值。顺便问下专家建议。',
            '从当前事件和过去30分钟的溶解氧总体均值判断是否恢复正常。',
        ):
            with self.subTest(question=question):
                self.assertIsNone(event_history_query(question))

    def test_standalone_with_both_authorized_tools(self):
        request = SimpleNamespace(question=QUESTION, history=())
        for authorized in (_BOTH, (ACTIVE_EVENTS,), (WATER_QUALITY_HISTORY,), ()):
            with self.subTest(authorized=authorized):
                policy = ToolPolicy('assistant', True, authorized)
                self.assertEqual(event_history_for_turn(request, policy) is not None, authorized == _BOTH)
        request.history = (object(),)
        self.assertIsNone(event_history_for_turn(request, ToolPolicy('assistant', True, _BOTH)))


class EventHistoryWebTests(unittest.TestCase):
    setUp = web_fixtures.ActiveEventAssistantTests.setUp
    configure = web_fixtures.ActiveEventAssistantTests.configure
    body = web_fixtures.ActiveEventAssistantTests.body
    send_case = web_fixtures.ActiveEventAssistantTests.send_case

    def plans(self, streaming, arguments=_ARGUMENTS):
        if streaming:
            return [tool_chunks(ACTIVE_EVENTS, 'events'), tool_chunks(WATER_QUALITY_HISTORY, 'history', arguments),
                    final_chunks(_UNVERIFIED)]
        return [sdk_tool(ACTIVE_EVENTS, 'events', model=self.profile.model),
                sdk_tool(WATER_QUALITY_HISTORY, 'history', arguments, self.profile.model),
                sdk_final(_UNVERIFIED, model=self.profile.model)]

    def test_normal_and_streaming_use_both_receipts_and_scope_omitted_mean(self):
        simulator = Simulator(device_id='pond-b', mode='water-only',
            start=self.now - timedelta(minutes=2), session_id='event-history-combo')
        for _ in range(2):
            self.monitoring.ingest(simulator.advance(60))
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                self.configure(self.plans(streaming), selection=_BOTH, board_device_id='board-1')
                result, rows = self.send_case(QUESTION, streaming=streaming, device='pond-b')
                self.assertEqual(len(self.sdk.bodies), 3)
                system = self.sdk.bodies[0]['messages'][0]['content']
                self.assertIn('lookback_minutes=30', system)
                self.assertIn(f'先用 {ACTIVE_EVENTS}', system)
                self.assertIn('metrics=["dissolved_oxygen_mg_l"]', system)
                self.assertIn('的有效观测范围内未查到匹配事件', result['final_text'])
                self.assertIn('板端视觉（board-1）缺少观测', result['final_text'])
                self.assertIn('本轮历史查询未提供可靠窗口总体均值', result['final_text'])
                self.assertIn('北京时间 2026-11-09 17:30:00 至 2026-11-09 18:00:00', result['final_text'])
                self.assertIn('共 2 个可靠窗口，覆盖 6.7%', result['final_text'])
                self.assertNotIn('99 mg/L', result['final_text'])
                self.assertFalse(any(row['kind'] == 'preview' for row in rows))

    def test_positive_event_names_are_bound_to_their_sources(self):
        report = BoardFixtures.report(self)
        receipt = self.monitoring.repository.import_device_report(report,
            received_at=self.now, inbox_cursor=1, now=self.now)
        self.assertEqual(receipt['status'], 'accepted')
        self.configure(self.plans(False), selection=_BOTH, board_device_id='board-1')
        result, _ = self.send_case(QUESTION, streaming=False)
        self.assertIn('在模拟设备 pond-a的记录中查到溶解氧偏低风险（活动）', result['final_text'])
        self.assertIn('在设备报告 board-1的记录中查到设备视觉异常报告（旧版）（活动）', result['final_text'])
        self.assertIn('完整观测范围仍未知', result['final_text'])
        self.assertIn('未提供可靠窗口总体均值', result['final_text'])
        self.assertNotIn('当前正常', result['final_text'])

    def test_gate_rejects_missing_event_receipt_or_unmatched_history_arguments(self):
        final = sdk_final(_UNVERIFIED, model=self.profile.model)
        for plans in ([sdk_tool(WATER_QUALITY_HISTORY, arguments=_ARGUMENTS, model=self.profile.model), final],
                      self.plans(False, '{"lookback_minutes":10,"metrics":["dissolved_oxygen_mg_l"]}'),
                      self.plans(False, '{"lookback_minutes":30,"metrics":["ph"]}')):
            self.configure(plans, selection=_BOTH)
            response = self.client.post('/api/ai/messages', headers=self.headers, json=self.body(question=QUESTION))
            self.addCleanup(response.close)
            result = response.get_json()['result']
            self.assertEqual(result['error_code'], 'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
            self.assertEqual(result['final_text'], '')
