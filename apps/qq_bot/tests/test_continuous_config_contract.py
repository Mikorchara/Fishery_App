"""Continuous configuration cannot silently widen legacy channel budgets."""
from dataclasses import asdict
import unittest

from apps.ai_service.channel import ChannelBudget
from apps.ai_service.channel_management_continuous import ContinuousChannelBudget
from apps.qq_bot.ai_configuration import QQAIConfig, QQAIGrant
from apps.qq_bot.ai_coordinator import QQAICoordinator


class ContinuousConfigContractTests(unittest.TestCase):
    def config(self, version, tokens):
        grant = QQAIGrant('test-group', ('test-member',), 'sim-pond-1')
        return dict(schema_version=version, enabled=True,
                    preset_id='dashscope-qwen38-flash-r1',
                    budget=dict(max_output_tokens=tokens, turn_timeout_s=90),
                    grants=[{**asdict(grant), 'members': list(grant.members), 'tools': list(grant.tools)}])

    def test_4096_is_new_channel_only_and_still_binds_per_turn_timeout(self):
        value = QQAIConfig.from_dict(self.config(2, 4096))
        self.assertIs(type(value.budget), ContinuousChannelBudget)
        self.assertEqual(value.budget.turn_timeout_s, 90)
        with self.assertRaises(Exception): QQAIConfig.from_dict(self.config(1, 4096))
        legacy = QQAIConfig.from_dict(self.config(1, 2048))
        self.assertIs(type(legacy.budget), ChannelBudget)
        for invalid in (0, 4097, True, 1.5, '2048'):
            with self.subTest(invalid=invalid), self.assertRaises(Exception):
                QQAIConfig.from_dict(self.config(2, invalid))
        altered = self.config(2, 2048)
        altered['budget']['turn_timeout_s'] = 91
        with self.assertRaises(Exception): QQAIConfig.from_dict(altered)

    def test_tools_help_is_free_in_continuous_without_business_keyword_gate(self):
        # Only deterministic help aliases are new; business language still
        # reaches the shared Agent instead of growing an intent whitelist.
        coordinator = object.__new__(QQAICoordinator)
        from apps.qq_bot.management_run import ManagementRun
        coordinator.session_run = object.__new__(ManagementRun)
        coordinator.session_run._continuous = True
        for question in ('工具', '/工具', '有什么工具', '你能做什么', '/帮助'):
            intent = coordinator.classify(question)
            self.assertEqual(intent.kind, 'capabilities')
            self.assertIn('当前水质（只读）', intent.text)
            self.assertNotIn('共享额度', intent.text)
        for question in ('当前季节易发疾病？', 'pH为什么重要？', '这些数据可靠吗？'):
            self.assertEqual(coordinator.classify(question).kind, 'agent')
        self.assertEqual(coordinator.classify('/未知指令').kind, 'unsupported')
        self.assertEqual(coordinator.classify('/当前水质').kind, 'fixed')


if __name__ == '__main__':
    unittest.main()
