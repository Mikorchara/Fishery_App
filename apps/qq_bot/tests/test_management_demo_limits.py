"""Display reliability without relaxing tool arguments or paid authorization."""
import json
import unittest

from apps.qq_bot.management_limits import ManagementRunLimits
from apps.qq_bot.management_config import load_request, check_request
from apps.qq_bot.run_consent import RunLimits
from apps.qq_bot.tests import test_management_live as fixture


class ManagementDemoTests(unittest.TestCase):
    setUp = fixture.ManagementLiveTests.setUp
    factory = fixture.ManagementLiveTests.factory
    compose = fixture.ManagementLiveTests.compose
    receive = fixture.ManagementLiveTests.receive
    ask = fixture.ManagementLiveTests.ask

    def test_budget_only_six_turns_then_safe_notice_and_fixed_query(self):
        value = json.loads(self.path.read_text())
        value['limits'] = dict(max_turns=None, seconds=7200, total_budget_cny='9.67')
        self.path.write_text(json.dumps(value))
        self.request = load_request(self.path)
        _, summary = check_request(self.path, offline=True)
        self.assertTrue(summary['limits']['budget_only'])
        self.assertEqual(summary['limits']['max_turns'], 6)
        self.compose()
        for _ in range(6):
            self.assertEqual(self.ask()['state'], 'DELIVERED')
        self.assertEqual(len(self.http), 6)
        self.assertEqual(self.host.ledger.report()['reserved_cost_cny'], '9.666360')
        self.assertEqual(self.receive('解释一下养殖概念', member='member-b')[0], 'QQ_REPLY_API_ACCEPTED')
        self.assertIn('预算预留已用完', self.posts[-1]['content'])
        self.assertEqual(self.receive('查询当前水质。', member='member-b')[0], 'QQ_REPLY_API_ACCEPTED')
        self.assertIn('SIMULATOR', self.posts[-1]['content'])
        self.assertEqual(self.receive('/清空会话', member='member-b')[0], 'QQ_REPLY_API_ACCEPTED')
        self.assertEqual(self.host.ledger.report()['consumed_turns'], 6)
        self.assertEqual(len(self.http), 6)

    def test_exact_aliases_zero_model_no_history_and_no_permission_expansion(self):
        self.compose()
        for text in ('查询水质', '查询当前水质', '查询当前水质。'):
            self.assertEqual(self.receive(text)[0], 'QQ_REPLY_API_ACCEPTED')
        self.assertEqual(self.http, [])
        self.assertEqual(self.host.store.counts()['turns'], 0)
        self.assertEqual(self.host.ledger.report()['consumed_turns'], 0)
        self.assertEqual(self.receive('查询当前水质', member='outsider')[0], 'MEMBER_DENIED')
        self.assertEqual(len(self.posts), 3)
        from apps.qq_bot.hybrid_intent import classify
        self.assertEqual(classify('查询当前水质 其他设备').kind, 'agent')
        self.assertEqual(classify('查询当前水质', command_priority=False).kind, 'agent')

    def test_limits_are_finite_strict_and_legacy_unchanged(self):
        self.assertEqual(RunLimits().max_turns, 5)
        with self.assertRaisesRegex(Exception, 'INVALID_RUN_LIMITS'):
            RunLimits(max_turns=6, total_budget_cny='100')
        for kwargs in (dict(max_turns=True), dict(seconds=28801), dict(total_budget_cny='NaN'),
                       dict(total_budget_cny='2001'), dict(max_turns=0), dict(max_turns=1001)):
            with self.assertRaises(Exception):
                ManagementRunLimits(**kwargs)
        with self.assertRaisesRegex(Exception, 'RUN_BUDGET_INSUFFICIENT'):
            ManagementRunLimits(max_turns=None, total_budget_cny='1')
        with self.assertRaisesRegex(Exception, 'RUN_BUDGET_INSUFFICIENT'):
            ManagementRunLimits(max_turns=100, total_budget_cny='8.06')
        self.assertEqual(ManagementRunLimits(max_turns=None, total_budget_cny='100').max_turns, 62)
