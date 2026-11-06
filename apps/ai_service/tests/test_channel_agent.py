"""QQ Web Agent output and scope checks using finite, detached source metadata."""
from dataclasses import replace
import unittest

from apps.ai_backend.tools.contracts import ToolStatus
from apps.ai_service.channel_management_agent import AgentChannelBudget, AgentChannelResult, prepared_scope
from apps.ai_service.channel_agent_presentation import present
from apps.ai_service.channel_management_continuous import ContinuousChannelBudget
from apps.ai_service.runtime.sources import TurnSourceReceipt, TurnSource
from apps.qq_bot.conversations import ConversationOptions


class ChannelAgentTests(unittest.TestCase):
    def answer(self,text,receipts=(),notes=()):
        return AgentChannelResult(True,None,None,text,'revision',branch='tools' if receipts else 'general',
            model_requests=len(receipts)+1,tool_executions=len(receipts),receipts=receipts,source_notes=notes)

    def test_general_is_plain_text_and_not_old_json_or_business_keyword_filter(self):
        for text in ('什么是溶解氧？它是溶解在水中的氧气。',
                     '水温20°C仅是举例。单凭聊天不能确诊鱼病。',
                     '如果当前水质正常，仍应定期观察。',
                     '我不能确认当前水质正常。是否需要查询？'):
            result=present(self.answer(text))
            self.assertTrue(result.allowed)
            self.assertIn(text,result.text)

    def test_explicit_claim_errors_are_distinct_and_do_not_fabricate_evidence(self):
        for text,code in (('我已查询当前水质。','AGENT_CURRENT_SOURCE_MISSING'),
                          ('已经统计最近30分钟数据。','AGENT_HISTORY_SOURCE_MISSING'),
                          ('已经检索项目资料。','AGENT_KNOWLEDGE_SOURCE_MISSING'),
                          ('已关闭增氧设备。','AGENT_UNSUPPORTED_OPERATION_CLAIM')):
            with self.subTest(text=text):
                result=present(self.answer(text))
                self.assertFalse(result.allowed)
                self.assertEqual(result.code,code)
                self.assertFalse(result.history_allowed)

    def test_knowledge_receipt_does_not_authorize_current_query_claim(self):
        receipt=TurnSourceReceipt(frozenset({TurnSource.RETRIEVED_PROJECT_EVIDENCE}),
            'search_fishery_knowledge',ToolStatus.OK,project_search_completed=True,evidence_count=1)
        accepted=present(self.answer('已经检索项目资料。',[receipt],['项目知识：1条背景证据。']))
        self.assertTrue(accepted.allowed)
        refused=present(self.answer('我已查询当前水质。',[receipt],['项目知识：1条背景证据。']))
        self.assertEqual(refused.code,'AGENT_CURRENT_SOURCE_MISSING')
        self.assertNotIn('SIMULATOR',refused.text)

    def test_too_long_or_empty_uses_specific_notice_without_retry_or_truncated_source(self):
        empty=present(self.answer(''))
        self.assertEqual(empty.code,'AGENT_EMPTY_REPLY')
        lengthy=present(self.answer('字'*1600,(),('历史窗口：非当前事实。',)))
        self.assertEqual(lengthy.code,'AGENT_REPLY_TOO_LONG')
        self.assertIn('历史窗口：非当前事实。',lengthy.text)
        self.assertNotIn('字'*20,lengthy.text)

    def test_new_scope_is_four_tools_and_existing_bounded_loop_budget(self):
        scope=prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True),4096)
        self.assertEqual(len(scope['runtime']['tools']),4)
        self.assertEqual(scope['execution']['mode'],'BOUNDED_MULTI_ROUND')
        self.assertEqual([scope['execution'][k] for k in ('max_tool_calls','max_tool_rounds','max_model_requests')],[2,2,3])
        self.assertEqual(scope['execution']['turn_timeout_s'],90)
        self.assertEqual(scope['execution']['max_output_tokens'],4096)
        self.assertNotEqual(type(AgentChannelBudget()),type(ContinuousChannelBudget()))

    def test_history_metadata_distinguishes_knowledge_from_observation(self):
        receipt=TurnSourceReceipt(tool_name='search_fishery_knowledge',tool_status=ToolStatus.NO_MATCH,
            project_search_completed=True)
        value=self.answer('无匹配资料。',(receipt,))
        times,flags=value.history_metadata()
        self.assertEqual(times,())
        self.assertEqual(flags,('agent','knowledge'))
