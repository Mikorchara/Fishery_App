"""Delivered QQ comparison choices use the existing bound history and query path."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest
from unittest.mock import patch

from apps.ai_service.business_tools.current_water_quality import CURRENT_WATER_QUALITY
from apps.ai_service.runtime.history_comparison import CLARIFICATION
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.qq_bot.agent_conversations import AgentConversationStore
from apps.qq_bot.contracts import BotError
from apps.qq_bot.conversations import ConversationOptions
from apps.qq_bot.tests import test_management_agent as fixture
from apps.qq_bot.tests.test_conversations import key
from apps.simulator.generator import Simulator


OLD = '我记录的pH为7.2；我记录的溶解氧是8.1 mg/L。'
QUESTION = '跟上次比呢？'
DO_CHOICE = '那就比一下溶氧吧'
DO_COMPARISON = '跟这段对话里我最近一次记录的溶解氧比'


class AgentClarificationStoreTests(unittest.TestCase):
    def setUp(self):
        self.tick = 10.0
        self.store = AgentConversationStore(ConversationOptions(trigger_mode='mention_ai', memory_enabled=True),
            monotonic=lambda: self.tick)
        self.addCleanup(self.store.close)

    def offer(self, *, offered=True):
        snapshot = self.store.snapshot(key(), focus=QUESTION)
        try:
            self.assertEqual(self.store.commit(snapshot, turn_id=str(self.tick), text=CLARIFICATION,
                text_sha256=hashlib.sha256(CLARIFICATION.encode()).hexdigest(),
                accepted_at='2026-11-24T00:00:00+00:00', source_times=(),
                source_flags=('general', 'model_knowledge', 'NO_OBSERVATION'), clarification_offered=offered),
                'HISTORY_COMMITTED')
        finally:
            self.store.release(snapshot)

    def choose(self, text=DO_CHOICE, *, water_allowed=True, **identity):
        scope = key(**identity)
        offer, continuation = self.store.clarification_candidate(scope, text, water_allowed=water_allowed)
        return continuation if self.store.consume_clarification(scope, offer) else None

    def test_bound_offer_is_one_use_even_for_concurrent_replies(self):
        self.offer()
        for field in ('member_id', 'device_id', 'policy_revision', 'binding_revision', 'epoch'):
            with self.subTest(field=field):
                self.assertIsNone(self.choose(**{field: 'another'}))
        with ThreadPoolExecutor(2) as executor:
            choices = list(executor.map(lambda _: self.choose(), range(2)))
        self.assertCountEqual(choices, [DO_COMPARISON, None])

    def test_offer_expires_or_is_discarded_on_new_topic_and_clear(self):
        self.offer()
        self.tick += 120
        self.assertIsNone(self.choose())
        self.offer()
        self.assertIsNone(self.choose('解释什么是pH'))
        self.assertIsNone(self.choose())
        self.tick += 1
        self.offer()
        self.store.clear(key())
        self.assertIsNone(self.choose())
        self.tick += 1
        self.offer()
        self.assertIsNone(self.choose('pH', water_allowed=False))
        self.assertIsNone(self.choose())
        self.tick += 1
        self.offer()
        self.assertEqual(self.choose('就比pH'), '跟这段对话里我最近一次记录的pH比')

    def test_general_reply_alone_cannot_advance_a_comparison(self):
        self.offer(offered=False)
        self.assertIsNone(self.choose('就比pH'))


class AgentClarificationEndToEndTests(unittest.TestCase):
    setUp = fixture.ManagementAgentTests.setUp
    compose = fixture.ManagementAgentTests.compose
    factory = fixture.ManagementAgentTests.factory
    receive = fixture.ManagementAgentTests.receive
    ask = fixture.ManagementAgentTests.ask

    def test_acceptance_then_single_metric_uses_original_user_record_and_current_tool(self):
        self.compose()
        self.general_text = '记下了你提供的自述值。'
        self.assertEqual(self.ask(OLD)['history_code'], 'HISTORY_COMMITTED')
        self.assertEqual(self.ask(QUESTION)['history_code'], 'HISTORY_COMMITTED')
        self.assertIn(CLARIFICATION, self.posts[-1]['content'])
        self.assertEqual(self.host.turns[-1]['tool_executions'], 0)

        code, task = self.receive(DO_CHOICE, member='member-b')
        self.assertEqual(code, 'AI_ADMITTED')
        self.assertEqual(self.scheduler.wait(task, 95)['history_code'], 'HISTORY_COMMITTED')
        self.assertEqual(self.http[-1]['messages'][-1]['content'], DO_CHOICE)

        self.general_text = '溶解氧为 99 mg/L。'
        self.plan = ((CURRENT_WATER_QUALITY, {}),)
        before = len(self.http)
        with patch.object(self.host, 'begin', side_effect=BotError('RUN_PERMIT_REQUIRED')):
            self.assertEqual(self.receive(DO_CHOICE), ('RUN_PERMIT_REQUIRED', None))
        self.assertEqual(len(self.http), before)

        now = datetime.now(timezone.utc)
        repository = MonitoringRepository(self.root / 'instance/monitoring.sqlite3', require_existing=True)
        monitoring = MonitoringService(repository, clock=lambda: now)
        simulator = Simulator(device_id='sim-pond-1', start=now-timedelta(seconds=10),
            session_id='clarification-source', mode='water-only')
        self.assertEqual(monitoring.ingest(simulator.advance())['status'], 'accepted')
        self.assertEqual(self.ask(DO_CHOICE)['history_code'], 'HISTORY_COMMITTED')
        self.assertEqual(self.http[-2]['messages'][-1]['content'], DO_COMPARISON)
        payload, = [json.loads(m['content']) for m in self.http[-1]['messages'] if m['role'] == 'tool']
        value = payload['water_quality']['dissolved_oxygen_mg_l']
        reply = self.posts[-1]['content']
        self.assertIn(f'溶解氧为 {value} mg/L', reply)
        self.assertIn('自述的溶解氧读数为 8.1 mg/L', reply)
        self.assertIn('相比，读数下降', reply)
        self.assertNotIn('溶解氧为 99 mg/L', reply)

        self.plan = ()
        self.general_text = '需要进一步说明要比较什么。'
        self.assertEqual(self.ask(DO_CHOICE)['history_code'], 'HISTORY_COMMITTED')
        current = self.http[-1]['messages']
        self.assertEqual(current[-1]['content'], DO_CHOICE)
        self.assertIn(DO_CHOICE, current[1]['content'])
        self.assertNotIn(DO_COMPARISON, current[1]['content'])

    def test_unknown_offer_delivery_never_arms_short_reply(self):
        self.compose()
        self.general_text = '记录来自用户自述。'
        self.assertEqual(self.ask(OLD)['history_code'], 'HISTORY_COMMITTED')
        self.outcomes[0] = 'UNKNOWN'
        self.assertEqual(self.ask(QUESTION)['state'], 'DELIVERY_UNKNOWN')
        self.assertEqual(self.ask('pH')['history_code'], 'HISTORY_COMMITTED')
        self.assertEqual(self.http[-1]['messages'][-1]['content'], 'pH')
        self.assertEqual(self.host.turns[-1]['tool_executions'], 0)
