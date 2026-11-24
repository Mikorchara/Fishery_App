import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

from apps.ai_service.business_tools.current_water_quality import CURRENT_WATER_QUALITY
from apps.ai_service.runtime.history_comparison import OXYGEN, comparison_for_history
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.qq_bot.tests import test_management_agent as fixtures
from apps.simulator.generator import Simulator


QUESTION = '跟这段对话里我最近一次记录的溶解氧比？'


class ComparisonSelectionTests(unittest.TestCase):
    def test_latest_self_report_scopes_ambiguity_and_device(self):
        trusted = SimpleNamespace(user='我上次记录的溶解氧是 7.3 mg/L。', assistant='本轮背景。')
        for user in ('设备 other：我上次记录的溶解氧是 9.4 mg/L。',
                     '我记录的溶解氧是 7.1 mg/L；我记录的溶解氧是 7.5 mg/L。',
                     '我记录的溶解氧是 9.4%'):
            with self.subTest(user=user):
                other = SimpleNamespace(user=user, assistant='我查到了 4.5 mg/L。')
                selected = comparison_for_history(QUESTION, (trusted, other), 'sim-pond-1')
                self.assertEqual(selected.metric, OXYGEN)
                self.assertIsNone(selected.value)
        ordinary = SimpleNamespace(user='什么是溶解氧？', assistant='假设 5.9 mg/L。')
        selected = comparison_for_history(QUESTION, (trusted, ordinary), 'sim-pond-1')
        self.assertEqual((selected.prior_index, selected.value), (0, Decimal('7.3')))

    def test_adjacent_two_distinct_metrics_needs_clarification(self):
        turn = SimpleNamespace(user='我记录的pH是7.2；我记录的溶解氧是7.3 mg/L。')
        self.assertIsNone(comparison_for_history('跟上次比呢？', (turn,), 'pond').metric)
        self.assertIsNone(comparison_for_history('跟上次比，加上我的用药记录？', (turn,), 'pond'))


class BoundQQComparisonTests(unittest.TestCase):
    setUp = fixtures.ManagementAgentTests.setUp
    compose = fixtures.ManagementAgentTests.compose
    receive = fixtures.ManagementAgentTests.receive
    ask = fixtures.ManagementAgentTests.ask
    factory = fixtures.ManagementAgentTests.factory

    def test_exact_comparison_uses_referenced_user_value_and_latest_two_turns(self):
        self.compose()
        for question in ('我上次记录的溶解氧是 7.3 mg/L。', '什么是水温？', '什么是pH？', '水质监测能做什么？'):
            self.assertEqual(self.ask(question)['history_code'], 'HISTORY_COMMITTED')
        self.plan = ((CURRENT_WATER_QUALITY, {}),)
        self.general_text = '旧溶解氧是 9.4 mg/L。'
        now = datetime.now(timezone.utc)
        repository = MonitoringRepository(self.root / 'instance/monitoring.sqlite3', require_existing=True)
        monitoring = MonitoringService(repository, clock=lambda: now)
        simulator = Simulator(device_id='sim-pond-1', start=now-timedelta(seconds=10),
                              session_id='comparison-source', mode='water-only')
        self.assertEqual(monitoring.ingest(simulator.advance())['status'], 'accepted')
        self.assertEqual(self.ask(QUESTION)['history_code'], 'HISTORY_COMMITTED')
        system, transcript, user = self.http[-2]['messages']
        self.assertIn(CURRENT_WATER_QUALITY, system['content'])
        self.assertEqual(user['content'], QUESTION)
        self.assertEqual(len(json.loads(transcript['content'])['turns']), 3)
        self.assertIn('7.3 mg/L', transcript['content'])
        self.assertNotIn('什么是水温', transcript['content'])
        data = json.loads(self.http[-1]['messages'][-1]['content'])['water_quality']['dissolved_oxygen_mg_l']
        body = self.posts[-1]['content']
        self.assertIn(f'{data} mg/L', body)
        self.assertIn('自述的溶解氧读数为 7.3 mg/L', body)
        self.assertNotIn('9.4 mg/L', body)
