"""Offline differential checks of the selected provider input and turn metadata."""

import json
import unittest

from apps.ai_backend.history_projection import (
    DEFAULT_HISTORY_PROJECTION,
    ProjectionId,
    project_retained_history,
)
from apps.ai_backend.tool_conversation import ToolExecutionMode
from apps.ai_backend.tests.support import final_chunks, sdk_final, sdk_tool, tool_chunks
from apps.ai_service.business_tools.current_water_quality import CURRENT_WATER_QUALITY
from apps.ai_service.runtime.assistant import (
    AssistantContextBuilder,
    AssistantHistoryTurn,
    AssistantRequest,
)
from apps.ai_service.runtime.history_selection import project_turn_history
from apps.ai_service.runtime.sources import SourceRequirement
from apps.management_web.tests import test_active_event_assistant as web_fixtures


class TurnHistorySelectionTests(unittest.TestCase):
    history = (
        AssistantHistoryTurn("我记得溶解氧是 5.9 mg/L。", "记录的是你当时的读数。", "2026-11-22T01:00:00+08:00"),
        AssistantHistoryTurn("另一台设备的溶解氧是 7.3 mg/L。", "这是另一台设备的记录。", "2026-11-22T02:00:00+08:00"),
    )

    def project(self, question, *, water_allowed=True, projection=DEFAULT_HISTORY_PROJECTION,
                requirement=SourceRequirement.AUTO, history=None):
        request = AssistantRequest(
            "dashscope-qwen38-flash-r1", question, self.history if history is None else history,
            source_requirement=requirement,
        )
        native = AssistantContextBuilder().build(request, execution_mode=ToolExecutionMode.BOUNDED_MULTI_ROUND)
        baseline = project_retained_history(request, native, projection)
        candidate = project_turn_history(request, native, projection, water_allowed=water_allowed)
        return request, baseline, candidate

    def test_explicit_current_readout_omits_stale_values_but_preserves_system_question_and_received_count(self):
        for question in ("当前溶解氧是多少？", "请问现在的溶解氧读数为多少？", "请帮我查一下 此刻的溶解氧数值。"):
            with self.subTest(question=question):
                request, (baseline, previous_bytes), (candidate, selected_bytes) = self.project(question)
                original_messages = baseline.model_request.messages
                old_values = json.loads(original_messages[1].content)["turns"]
                self.assertEqual([pair["messages"][0]["text"] for pair in old_values],
                                 [turn.user for turn in self.history])
                self.assertEqual(candidate.model_request.messages, (original_messages[0], original_messages[-1]))
                self.assertEqual(request.history, self.history)
                self.assertEqual(candidate.history_turns_received, 2)
                self.assertEqual(candidate.history_turns_sent, 0)
                self.assertEqual(candidate.history_trimmed, 2)
                self.assertGreater(previous_bytes, selected_bytes)
                self.assertEqual(candidate.history_bytes_sent, 2)

    def test_comparison_references_and_non_readout_queries_keep_identical_context(self):
        questions = (
            "跟上次比呢？", "当前溶解氧是多少，和上次比呢？", "查一下刚才那台设备当前的溶解氧。",
            "请解释溶解氧。", "当前溶解氧偏低吗？", "当前溶解氧怎么样？", "当前水温是多少？",
            "当前发生了什么事件，溶解氧是多少？", "过去 30 分钟溶解氧是多少？", "溶解氧是多少？",
        )
        for question in questions:
            with self.subTest(question=question):
                _, baseline, candidate = self.project(question)
                self.assertEqual(baseline, candidate)

    def test_default_history_policy_still_governs_other_paths(self):
        options = (
            {"water_allowed": False},
            {"projection": ProjectionId.CURRENT_NATIVE},
            {"requirement": SourceRequirement.CURRENT_OBSERVATION_QUERY},
            {"requirement": SourceRequirement.HISTORICAL_WATER_QUERY},
            {"history": ()},
        )
        for option in options:
            with self.subTest(option=option):
                _, baseline, candidate = self.project("当前溶解氧是多少？", **option)
                self.assertEqual(baseline, candidate)


class TurnHistorySelectionWebTests(unittest.TestCase):
    setUp = web_fixtures.ActiveEventAssistantTests.setUp
    configure = web_fixtures.ActiveEventAssistantTests.configure
    body = web_fixtures.ActiveEventAssistantTests.body

    def test_normal_and_sse_keep_prior_value_only_for_the_followup(self):
        history = [{"user": "我记得上次的溶解氧是 5.9 mg/L。", "assistant": "记下了你当时的读数。",
                    "completed_at": "2026-11-08T01:00:00+08:00"}]
        for streaming in (False, True):
            for question, history_sent in (("当前溶解氧是多少？", 0), ("跟上次比呢？", 1)):
                with self.subTest(streaming=streaming, question=question):
                    wrong = '我查到当前溶解氧是 5.9 mg/L。'
                    plans = ([tool_chunks(CURRENT_WATER_QUALITY), final_chunks(wrong)] if streaming else [
                        sdk_tool(CURRENT_WATER_QUALITY, model=self.profile.model),
                        sdk_final(wrong, model=self.profile.model),
                    ])
                    self.configure(plans)
                    body = self.body(streaming=streaming, question=question)
                    response = self.client.post("/api/ai/messages" + ("/stream" if streaming else ""),
                        headers=self.headers, json={**body, "history": history})
                    self.addCleanup(response.close)
                    self.assertEqual(response.status_code, 200, response.get_json(silent=True))
                    if streaming:
                        rows = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines()
                                if line.startswith("data: ")]
                        self.assertEqual(rows[-1]["kind"], "final")
                        result = rows[-1]["result"]
                    else:
                        result = response.get_json()["result"]
                    self.assertTrue(result["successful_turn"], result.get("error_code"))
                    self.assertEqual(result["history_turns_received"], 1)
                    self.assertEqual(result["history_turns_sent"], history_sent)
                    self.assertEqual(len(self.sdk.bodies), 2)
                    for request in self.sdk.bodies:
                        self.assertEqual("5.9 mg/L" in json.dumps(request["messages"], ensure_ascii=False),
                                         bool(history_sent))
                    first_messages = self.sdk.bodies[0]["messages"]
                    self.assertEqual(first_messages[-1]["content"], question)
                    self.assertEqual(len(first_messages), 2 + history_sent)
                    tool_result = json.loads(self.sdk.bodies[-1]["messages"][-1]["content"])
                    self.assertEqual(tool_result["water_quality"]["dissolved_oxygen_mg_l"], 2.2)
                    if not history_sent:
                        self.assertIn('2.2 mg/L', result['final_text'])
                        self.assertIn('北京时间', result['final_text'])
                        self.assertNotIn('5.9 mg/L', result['final_text'])
                        if streaming:
                            self.assertFalse(any(row['kind'] == 'preview' for row in rows))

    def test_explicit_current_readout_without_current_receipt_cannot_publish(self):
        self.configure([sdk_final('当前溶解氧为 5.9 mg/L。', model=self.profile.model)])
        response = self.client.post('/api/ai/messages', headers=self.headers,
            json=self.body(question='当前溶解氧是多少？'))
        result = response.get_json()['result']
        self.assertEqual(result['error_code'], 'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
        self.assertEqual(result['final_text'], '')
