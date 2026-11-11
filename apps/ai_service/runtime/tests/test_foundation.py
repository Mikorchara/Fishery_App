"""Frozen business contracts and deterministic old/new differential. No Provider I/O."""
from dataclasses import asdict, replace
from datetime import datetime
import importlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.ai_backend import execution
from apps.ai_backend.contracts import Status
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.model_gateway import ProfileRegistry, ModelResponse, ModelToolCall, GatewayError
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.tool_conversation import (ToolCallingService, ToolExecutionMode,
    ToolModelTransport, ToolExecutionStep, ModelExecutionStep)
from apps.ai_backend.tools import ToolDefinition, ToolRegistry
from apps.ai_backend.tools.policy import ToolPolicy, ToolPolicyError
from apps.ai_backend.tests.support import ScriptedGateway
from apps.ai_service.runtime import assistant, sources, activity
from apps.ai_service.business_tools import active_events, current_water_quality, fishery_knowledge
from apps.ai_service.business_tools.registry import WATER_QUALITY_SCORE
from apps.ai_service.runtime.policy import UserToolPolicyStore


WATER, KNOWLEDGE, SCORE = current_water_quality.CURRENT_WATER_QUALITY, fishery_knowledge.SEARCH_FISHERY_KNOWLEDGE, WATER_QUALITY_SCORE
QWEN = assistant.ALLOWED_PRESET_IDS[0]
STAMP = '2026-10-16T00:00:00+00:00'


def water_payload(*, quality='valid', freshness='fresh', status='OK'):
    return {'status':status, 'water_quality':None if status == 'NO_DATA' else {
        'temperature_c':28.0, 'ph':None if quality == 'partial' else 7.5,
        'dissolved_oxygen_mg_l':2.2, 'quality':quality, 'freshness':freshness,
        'observed_at':STAMP,'retrieved_at':STAMP,'source':'fictional-monitoring'},
        'evaluated_at':STAMP, 'findings':[]}


def knowledge_payload(hit=True):
    items = [{'id':'fictional-id', 'category':'water_quality', 'source':'fictional-project',
              'text':'fictional-background', 'source_version':'fixture-1'}] if hit else []
    return {'status':'OK' if hit else 'NO_MATCH','result_count':len(items),
            'retrieval_mode':'portable','evidence':items}


def call(name=WATER, arguments='{}', identifier='call_1'):
    return ModelResponse(None, tool_calls=(ModelToolCall(identifier,name,arguments),), finish_reason='tool_calls')


def final(text='安全回答'):
    return ModelResponse(text, finish_reason='stop')


class FoundationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = assistant.assistant_profile(QWEN)
        self.runtime = ProfileRegistry([self.profile], CredentialStore(process_env={
            self.profile.credential_ref:'fictional-backend-key'})).snapshot(self.profile.profile_id)
        self.traces = JsonlTraceSink(self.root/'trace.jsonl',tool_names=(WATER,KNOWLEDGE,active_events.ACTIVE_EVENTS))
        self.called = []

    def registry(self, water=None, knowledge=None):
        def get_water():
            self.called.append(WATER)
            return water if water is not None else water_payload()
        def get_knowledge(arguments):
            self.called.append(KNOWLEDGE)
            return knowledge if knowledge is not None else knowledge_payload()
        return ToolRegistry((ToolDefinition(current_water_quality.WATER_DEFINITION,get_water),
            ToolDefinition(fishery_knowledge.KNOWLEDGE_DEFINITION,get_knowledge,fishery_knowledge.validate_arguments)))

    def send(self, responses, *, registry=None, requirement=sources.SourceRequirement.AUTO,
             mode=ToolExecutionMode.BOUNDED_MULTI_ROUND, history=(), handle=None, traces=None,
             tool_names=(WATER,KNOWLEDGE)):
        gateway = ScriptedGateway(responses)
        coordinator = ToolCallingService(gateway, registry or self.registry(), traces or self.traces,
            policy=ToolPolicy('assistant',True,tool_names),execution_mode=mode)
        handle = handle or execution.RequestHandle(summarize_tool=activity.tool_summary)
        handle.start()
        with execution.request_scope(handle):
            result = assistant.AssistantService(coordinator,execution_mode=mode).send(
                assistant.AssistantRequest(QWEN,'本轮问题',history,source_requirement=requirement),self.runtime)
        return result,handle


    def test_no_tool_imitation_no_receipt_and_unmet_requirement_no_commit(self):
        for requirement in sources.SourceRequirement:
            result, handle = self.send([final('[调用工具 search_fishery_knowledge] 已查询')], requirement=requirement)
            self.assertFalse(result.source_ledger.entries)
            self.assertEqual(result.to_dict()['successful_turn'],requirement == sources.SourceRequirement.AUTO)
            if requirement != sources.SourceRequirement.AUTO:
                self.assertEqual(result.error_code,'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
                self.assertEqual(result.final_text,'')
                self.assertEqual(handle.state,'FAILED')

    def test_water_business_matrix_preserves_query_operation_vs_observation(self):
        for payload in [water_payload(),water_payload(status='NO_DATA'),
                        water_payload(quality='partial'),water_payload(quality='invalid'),
                        water_payload(freshness='stale')]:
            with self.subTest(status=payload['status'],water=payload['water_quality']):
                result,_ = self.send([call(),final()],registry=self.registry(water=payload),
                    requirement=sources.SourceRequirement.CURRENT_OBSERVATION_QUERY)
                receipt = result.source_receipt
                self.assertTrue(receipt.observation_query_completed)
                self.assertEqual(receipt.has_observation,payload['status'] != 'NO_DATA')
                self.assertEqual(result.status,Status.COMPLETED)
                self.assertFalse(sources.requirement_satisfied(
                    sources.SourceRequirement.CURRENT_SCORE_EVALUATION,receipt))

    def test_knowledge_hit_and_no_match_are_distinct_from_current_fact(self):
        for hit in (False,True):
            result,_ = self.send([call(KNOWLEDGE,'{"query":"固定夹具"}'),final()],
                registry=self.registry(knowledge=knowledge_payload(hit)),
                requirement=sources.SourceRequirement.PROJECT_KNOWLEDGE_SEARCH)
            self.assertEqual(result.status,Status.COMPLETED)
            self.assertTrue(result.source_receipt.project_search_completed)
            self.assertEqual(result.source_receipt.has_project_evidence,hit)
            self.assertFalse(result.source_receipt.observation_query_completed)

    def test_event_query_completion_sources_and_public_activity(self):
        name = active_events.ACTIVE_EVENTS
        for status, observed, hit in (("NO_DATA", False, False), ("NO_ACTIVE_EVENTS", True, False), ("OK", True, True)):
            with self.subTest(status=status):
                observation = dict(observed_at=STAMP if observed else None,
                    quality="valid" if observed else "missing", freshness="fresh" if observed else "unknown",
                    connectivity="online" if observed else "never_received")
                source = dict(source_kind="simulator", device_id="fictional-private-device",
                    observations=[dict(observation, channel=channel) for channel in ("water", "visual")])
                cycles = [dict(channel="water", code="OXYGEN_LOW", lifecycle_state="ACTIVE",
                    severity="warning", occurred_at=STAMP, last_observed_at=STAMP,
                    current_data_quality={"freshness": "fresh"}, description="fictional-raw-event-text")] if hit else []
                monitoring = SimpleNamespace(active_event_snapshot=lambda *_a, **_kw: (
                    datetime.fromisoformat(STAMP), [(source, cycles)]))
                payload = active_events.active_events_payload(monitoring, source["device_id"])
                registry = ToolRegistry((ToolDefinition(active_events.ACTIVE_EVENTS_DEFINITION, lambda: payload),))
                result, _ = self.send([call(name), final()], registry=registry, tool_names=(name,),
                    requirement=sources.SourceRequirement.ACTIVE_EVENTS_QUERY)
                self.assertEqual(result.status, Status.COMPLETED)
                receipt = result.source_receipt
                self.assertTrue(receipt.active_events_query_completed)
                self.assertEqual(receipt.active_events_status, status)
                self.assertEqual(receipt.active_events_count, int(hit))
                self.assertEqual(receipt.sources, {sources.TurnSource.ACTIVE_EVENT_SUMMARIES} if hit else set())
                self.assertFalse(receipt.observation_query_completed)
                self.assertFalse(receipt.history_query_completed)
                summary = result.to_dict()["activity"]["steps"][1]
                self.assertEqual(summary["display_name"], "活动事件查询")
                self.assertEqual(summary["evaluated_at"], STAMP)
                public = json.dumps(result.to_dict(), ensure_ascii=False)
                self.assertNotIn("fictional-private-device", public)
                self.assertNotIn("fictional-raw-event-text", public)
                self.assertNotIn("OXYGEN_LOW", public)

    def test_malformed_event_tool_payload_cannot_satisfy_source_gate(self):
        name = active_events.ACTIVE_EVENTS
        malformed = {"status": "OK", "query_completed": True, "items": []}
        registry = ToolRegistry((ToolDefinition(active_events.ACTIVE_EVENTS_DEFINITION, lambda: malformed),))
        result, handle = self.send([call(name), final()], registry=registry, tool_names=(name,),
            requirement=sources.SourceRequirement.ACTIVE_EVENTS_QUERY)
        self.assertEqual(result.error_code, "ASSISTANT_SOURCE_REQUIREMENT_UNMET")
        self.assertEqual(handle.state, "FAILED")
        self.assertEqual(result.final_text, "")
        self.assertFalse(result.source_receipt.active_events_query_completed)
        self.assertFalse(result.source_receipt.sources)

    def test_invalid_arguments_never_run_handler_followup_receipt_or_commit(self):
        for args in ('{"device_id":"private-fixture-value"}','{"query":"wrong"}'):
            result,_ = self.send([call(arguments=args)])
            self.assertEqual(result.error_code,'INVALID_TOOL_ARGUMENTS')
            self.assertFalse(self.called)
            self.assertFalse(result.to_dict()['successful_turn'])
            self.assertFalse(result.source_receipt.observation_query_completed)
            safe=json.dumps(result.to_dict())+self.traces.path.read_text(encoding='utf-8')
            self.assertNotIn('private-fixture-value',safe)
            self.assertEqual(result.to_dict()['activity']['counts']['tools_executed'],0)

    def test_ledger_keeps_two_results_and_legacy_projection_fails_closed(self):
        result,_ = self.send([call(),call(KNOWLEDGE,'{"query":"固定"}','call_2'),final()])
        self.assertEqual(self.called,[WATER,KNOWLEDGE])
        self.assertEqual([e.execution_seq for e in result.source_ledger.entries],[2,4])
        self.assertEqual(len(result.execution.steps),5)
        self.assertIsNone(result.to_dict()['tool_activity'])
        with self.assertRaises(ValueError): _=result.source_receipt
        self.assertTrue(sources.requirement_satisfied_by_ledger(
            sources.SourceRequirement.CURRENT_OBSERVATION_QUERY,result.source_ledger))
        self.assertTrue(sources.requirement_satisfied_by_ledger(
            sources.SourceRequirement.PROJECT_KNOWLEDGE_SEARCH,result.source_ledger))

    def test_later_provider_or_tool_failure_keeps_audit_but_no_success(self):
        for second in [GatewayError('HTTP_429'),call(KNOWLEDGE,'{}','call_2')]:
            result,_ = self.send([call(),second])
            self.assertEqual(result.status,Status.FAILED)
            self.assertEqual(result.final_text,'')
            self.assertTrue(result.source_ledger.entries[0].receipt.observation_query_completed)
            self.assertFalse(result.to_dict()['successful_turn'])

    def test_budget_multiple_calls_duplicates_and_third_request_final_only(self):
        multiple = ModelResponse(None, tool_calls=(ModelToolCall('a',WATER,'{}'),
            ModelToolCall('b',KNOWLEDGE,'{"query":"x"}')),finish_reason='tool_calls')
        cases = [([multiple],'TOOL_CALL_LIMIT',0),
            ([call(),call(identifier='call_2')],'TOOL_REQUEST_ALREADY_EXECUTED',1),
            ([call(),call(KNOWLEDGE,'{"query":"x"}','call_2'),call(identifier='call_3')],'TOOL_ROUND_LIMIT',2)]
        for responses,code,count in cases:
            self.called.clear()
            result,_ = self.send(responses)
            self.assertEqual(result.error_code,code)
            self.assertEqual(len(self.called),count)
            self.assertLessEqual(result.execution.usage.request_count,3)
        result,_ = self.send([call(),call(KNOWLEDGE,'{"query":"x"}','call_2')],
            mode=ToolExecutionMode.SINGLE_ROUND)
        self.assertEqual(result.error_code,'TOOL_ROUND_LIMIT')

    def test_trace_failure_or_deadline_during_commit_cannot_publish_final(self):
        with patch.object(self.traces,'record_assistant',side_effect=OSError('fictional-private-path')):
            result,_ = self.send([final()])
        self.assertEqual(result.error_code,'TRACE_WRITE_ERROR')
        self.assertEqual(result.final_text,'')
        handle=execution.RequestHandle(); original=self.traces.record_assistant
        def late(*a,**kw):
            original(*a,**kw);handle._deadline=0.0
        with patch.object(self.traces,'record_assistant',side_effect=late):
            result,_ = self.send([final()],handle=handle)
        self.assertEqual(result.error_code,'TOTAL_TIMEOUT')
        self.assertFalse(result.to_dict()['successful_turn'])
        self.assertEqual(handle.state,'FAILED')


    def test_stored_score_policy_preserved_but_never_bound_or_exposed(self):
        registry=self.registry();store=UserToolPolicyStore(self.root/'policy',registry)
        data=store.default_selections()
        data['modes']['assistant']['selected_tools']=[WATER,SCORE,KNOWLEDGE]
        store.save(data)
        self.assertEqual(store.load(),data)
        self.assertEqual(store.effective()['assistant'].exposed_tools,(WATER,KNOWLEDGE))
        self.assertNotIn(SCORE,registry.registered_names())
        with self.assertRaises(Exception):registry.lookup(SCORE)
        for names in [[WATER,WATER],['unknown_tool'],[False]]:
            bad=json.loads(json.dumps(data));bad['modes']['assistant']['selected_tools']=names
            with self.assertRaises(ToolPolicyError):store.save(bad)
