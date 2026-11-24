"""Question labels and entirely new public-API synthetic research data."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.qq_bot.management_config import ROOT, MARKER
from scripts.dev.qq_agent_cases import (CASES, CATEGORIES, CURRENT, CURATED_OXYGEN_SCENARIO,
    EVENT_NOTICE_CASES, EVENT_RESTRICTED_SCENARIO, HISTORY, KNOWLEDGE, RAG_CASES, SCORE,
    ABSENT_KNOWLEDGE_QUERY, SCENARIOS, create_fixture, refresh_fixture, validate_case_library)


class AgentResearchCaseTests(unittest.TestCase):
    def setUp(self):
        parent=ROOT/'outputs/test-tmp';parent.mkdir(parents=True,exist_ok=True)
        temporary=TemporaryDirectory(dir=parent);self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.now=datetime(2026,11,6,4,0,tzinfo=timezone.utc)
        for target in ('socket.socket.connect','socket.getaddrinfo',
                       'apps.ai_backend.credentials.CredentialStore.resolve'):
            guard=patch(target,side_effect=AssertionError('no real network or credentials'))
            guard.start();self.addCleanup(guard.stop)

    def fixture(self,scenario='fresh'):
        return create_fixture(self.root/scenario,scenario,clock=lambda:self.now)

    def test_44_unique_cases_cover_all_categories_scenarios_and_ordered_memory(self):
        self.assertEqual(len(CASES),44)
        self.assertEqual(len({c.id for c in CASES}),44)
        self.assertEqual(set(c.category for c in CASES),set(CATEGORIES))
        self.assertEqual(set(c.scenario for c in CASES),set(SCENARIOS)-{CURATED_OXYGEN_SCENARIO})
        self.assertEqual(validate_case_library(),CASES)
        memory=[c for c in CASES if c.conversation_id]
        self.assertEqual([c.turn for c in memory],[1,2,3,4,5])
        self.assertEqual({c.conversation_id for c in memory},{'oxygen-topic'})
        self.assertTrue(all('question' not in c.public() for c in CASES))
        self.assertTrue(all(c.public(include_question=True)['question']==c.question for c in CASES))

    def test_labels_accept_reasonable_tool_alternatives_without_counting_unknown_as_pass(self):
        cases={c.id:c for c in CASES}
        self.assertTrue(cases['G01'].tool_choice_matches(()))
        self.assertTrue(cases['G01'].tool_choice_matches((KNOWLEDGE,)))
        self.assertFalse(cases['G01'].tool_choice_matches((CURRENT,)))
        self.assertTrue(cases['C01'].tool_choice_matches((CURRENT,)))
        self.assertTrue(cases['C01'].tool_choice_matches((SCORE,)))
        self.assertTrue(cases['X01'].tool_choice_matches((HISTORY,CURRENT)))
        self.assertFalse(cases['X01'].tool_choice_matches((HISTORY,)))
        self.assertFalse(cases['C01'].tool_choice_matches((CURRENT,CURRENT)))
        self.assertIsNone(cases['A01'].tool_choice_matches(()))
        self.assertEqual(cases['K01'].required_tools,(KNOWLEDGE,))

    def test_opt_in_rag_cases_use_curated_papers_with_separate_simulated_history(self):
        from apps.ai_service.business_tools.fishery_knowledge import search_fishery_knowledge
        from apps.knowledge.repository import KnowledgeRepository
        from apps.knowledge.service import KnowledgeContentService

        self.assertEqual([case.id for case in RAG_CASES], ['R01', 'R02', 'R03', 'R04', 'R05', 'R06'])
        self.assertEqual(validate_case_library(CASES + RAG_CASES), CASES + RAG_CASES)
        self.assertTrue(all(case.scenario == CURATED_OXYGEN_SCENARIO for case in RAG_CASES))
        self.assertTrue(all(case.tool_choice_matches((KNOWLEDGE,)) for case in RAG_CASES[:-1]))
        self.assertTrue(RAG_CASES[-1].tool_choice_matches((HISTORY, KNOWLEDGE)))
        fixture = self.fixture(CURATED_OXYGEN_SCENARIO)
        knowledge = KnowledgeContentService(KnowledgeRepository(fixture.root/'knowledge.sqlite3', read_only=True))
        self.assertEqual(knowledge.list()['total'], 12)
        self.assertEqual(fixture.public()['synthetic_knowledge'], 'CURATED_OXYGEN_V2_LITERATURE_AND_NO_USER_DATA')
        expected = (('EXACT', '12.4%'), ('PARTIAL', '14.1%'), ('NO_MATCH', ''),
                    ('NO_MATCH', ''), ('EXACT', '3.76%'), ('EXACT', '8.9%'))
        for case, (coverage, value) in zip(RAG_CASES, expected, strict=True):
            with self.subTest(case=case.id):
                result = search_fishery_knowledge({'query': case.question}, service=knowledge, question=case.question)
                self.assertEqual(result.get('curated_oxygen', {}).get('coverage'), coverage)
                if value:
                    self.assertTrue(any(value in item['text'] for item in result['evidence']))
                else:
                    self.assertEqual(result['evidence'], [])
        history = fixture.service.query_water_history('sim-pond-1', lookback_minutes=30)
        self.assertEqual(history['status'], 'OK')
        self.assertEqual(history['counts']['matching_windows'], 30)
        self.assertEqual(fixture.public()['source'], 'SIMULATOR')

    def test_opt_in_event_notice_cases_only_restrict_new_research_grants(self):
        from apps.ai_service.management_policy import ManagementToolPolicyStore
        from apps.qq_bot.ai_configuration import load_ai_config
        from scripts.dev.check_qq_agent import _configure, build_plan

        selected = (CURRENT, KNOWLEDGE, HISTORY)
        cases = CASES + RAG_CASES + EVENT_NOTICE_CASES
        self.assertEqual(validate_case_library(cases), cases)
        self.assertEqual([case.id for case in EVENT_NOTICE_CASES], ['P01', 'P02', 'P03'])
        for case, tool_names in zip(EVENT_NOTICE_CASES, [(), (CURRENT,), (CURRENT,)], strict=True):
            self.assertEqual(case.scenario, EVENT_RESTRICTED_SCENARIO)
            self.assertTrue(case.tool_choice_matches(tool_names))
            self.assertFalse(case.tool_choice_matches((KNOWLEDGE,)))

        plan = build_plan(EVENT_NOTICE_CASES)
        fixture = self.fixture(EVENT_RESTRICTED_SCENARIO)
        request = _configure(fixture, self.root, 2048)
        grant = load_ai_config(request.inputs.ai_config).grants[0]
        policy = ManagementToolPolicyStore(request.inputs.policy_directory, None).snapshot()
        self.assertEqual(grant.tools, selected)
        self.assertEqual(policy.selected_tools, selected)
        self.assertEqual(policy.source, 'MANAGEMENT_OVERRIDE')
        self.assertEqual(plan['event_notice_fixture'], fixture.public()['event_notice_fixture'])
        self.assertFalse(plan['event_notice_fixture']['active_event_query_authorized'])
        self.assertEqual(plan['qq_network_requests'], 0)
        self.assertNotIn('event_notice_fixture', build_plan())
        self.assertIsNotNone(fixture.current_oracle()['water_values']['dissolved_oxygen_mg_l'])

    def test_five_scenarios_are_assessed_by_real_monitoring_domain(self):
        expected={
            'fresh':('valid','fresh','online'),
            'missing':('partial','fresh','online'),
            'stale':('valid','stale','offline'),
            'low_oxygen':('valid','fresh','online'),
            'no_data':('missing','unknown','never_received')}
        for scenario in expected:
            with self.subTest(scenario=scenario):
                fixture=self.fixture(scenario)
                oracle=fixture.current_oracle();dq=oracle['data_quality']
                self.assertEqual(tuple(dq[k] for k in ('quality','freshness','connectivity')),expected[scenario])
                hits=[f['code'] for f in oracle['findings'] if f['kind']=='WATER_RISK' and f['state']=='HIT']
                if scenario=='low_oxygen':self.assertIn('OXYGEN_CRITICAL_LOW',hits)
                if scenario in ('stale','no_data'):self.assertEqual(hits,[])
                self.assertEqual(fixture.windows_created,0 if scenario=='no_data' else 30)
                self.assertEqual(fixture.public()['source'],'SIMULATOR')
                self.assertFalse(fixture.public()['automatic_background_refresh'])
                self.assertFalse(fixture.public()['timestamps_rewritten'])
                if scenario=='missing':
                    self.assertIsNone(fixture.water_values['ph'])
                    self.assertEqual(oracle['metric_quality']['ph'],'missing')

    def test_public_seed_has_full_30_minute_history_and_bundled_background_only(self):
        fixture=self.fixture()
        from apps.knowledge.repository import KnowledgeRepository
        from apps.knowledge.service import KnowledgeContentService
        knowledge=KnowledgeContentService(KnowledgeRepository(fixture.root/'knowledge.sqlite3',read_only=True))
        self.assertEqual(knowledge.list()['total'],31)
        self.assertTrue(knowledge.search('增氧'))
        self.assertEqual(knowledge.search(ABSENT_KNOWLEDGE_QUERY),())
        history=fixture.service.query_water_history('sim-pond-1',lookback_minutes=30)
        self.assertEqual(history['status'],'OK')
        self.assertEqual(history['counts']['matching_windows'],30)
        self.assertEqual(history['coverage']['received_coverage_ratio'],1)
        self.assertEqual(fixture.service.query_water_history('sim-pond-1',lookback_minutes=60)['status'],'PARTIAL')
        marker=json.loads((fixture.root/'qq-isolated-instance.json').read_text(encoding='utf8'))
        self.assertEqual(marker,dict(contract=MARKER,root=str(fixture.root),instance_id='management-isolated',
            device_id='sim-pond-1',source='SIMULATOR'))

    def test_refresh_creates_new_samples_and_keeps_original_rows_unchanged(self):
        fixture=self.fixture('missing')
        original=fixture.service.repository.history('sim-pond-1','water')
        self.assertFalse(refresh_fixture(fixture))
        self.now+=timedelta(seconds=17)
        self.assertTrue(refresh_fixture(fixture))
        after=fixture.service.repository.history('sim-pond-1','water')
        old_by_id={row['batch_id']:row for row in original}
        self.assertEqual({row['batch_id']:row for row in after if row['batch_id'] in old_by_id},old_by_id)
        self.assertEqual(len(after),31)
        self.assertEqual(fixture.last_observed_at,self.now)
        self.assertEqual(fixture.refresh_windows,1)
        self.assertIsNone(fixture.water_values['ph'])
        self.assertEqual(fixture.current_oracle()['data_quality']['freshness'],'fresh')

    def test_slow_refresh_leaves_a_real_coverage_gap_instead_of_rewriting_history(self):
        fixture=self.fixture()
        before=fixture.last_observed_at
        self.now+=timedelta(minutes=5)
        self.assertTrue(refresh_fixture(fixture))
        row=fixture.service.repository.read('sim-pond-1','water')
        self.assertEqual(datetime.fromisoformat(row['payload']['window']['start']),self.now-timedelta(seconds=60))
        self.assertGreater(datetime.fromisoformat(row['payload']['window']['start']),before)
        history=fixture.service.query_water_history('sim-pond-1',lookback_minutes=30)
        self.assertEqual(history['status'],'PARTIAL')
        self.assertGreater(history['gaps']['total_s'],0)

    def test_stale_and_no_data_never_refresh_or_change_database(self):
        for scenario in ('stale','no_data'):
            fixture=self.fixture(scenario)
            path=fixture.root/'monitoring.sqlite3'
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            stamp=fixture.last_observed_at
            self.now+=timedelta(hours=1)
            self.assertFalse(refresh_fixture(fixture))
            self.assertEqual(fixture.last_observed_at,stamp)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            self.assertEqual(fixture.refresh_windows,0)

    def test_existing_or_outside_roots_fail_before_opening_or_overwriting(self):
        target=self.root/'already-there';target.mkdir();(target/'marker').write_text('keep')
        with patch('sqlite3.connect',side_effect=AssertionError('must not open existing DB')):
            for path in (target,ROOT.parent/'never-create-agent-research',self.root/'missing-parent'/'data'):
                with self.subTest(path=path):
                    with self.assertRaisesRegex(ValueError,'NEW_RESEARCH_OUTPUT_DIRECTORY_REQUIRED'):
                        create_fixture(path,'fresh',clock=lambda:self.now)
        self.assertEqual((target/'marker').read_text(),'keep')
        self.assertEqual(list(target.iterdir()),[target/'marker'])

    def test_naive_or_rollback_clock_does_not_forge_new_data(self):
        target=self.root/'naive'
        with self.assertRaisesRegex(ValueError,'RESEARCH_UTC_CLOCK_REQUIRED'):
            create_fixture(target,'fresh',clock=lambda:datetime(2026,11,6))
        self.assertFalse(target.exists())
        fixture=self.fixture()
        before=fixture.last_observed_at
        self.now-=timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError,'RESEARCH_CLOCK_ROLLBACK'):
            refresh_fixture(fixture)
        self.assertEqual(fixture.last_observed_at,before)


if __name__=='__main__':unittest.main()
