"""New continuous display contract; no sockets, credentials or existing data."""
from dataclasses import replace
import unittest

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel import ChannelBudget, SourceSummary, SourceMetric, SourceRule
from apps.ai_service.channel_hybrid import HybridResult
from apps.ai_service.channel_management_continuous import (
    ContinuousChannelBudget, INSTRUCTION, PROMPT_ID, prepared_scope, preparation_record)
from apps.ai_service.channel_natural_presentation import present, MAX_REPLY_CHARS
from apps.ai_service.channel_session_run import LeaseAuthority
from apps.qq_bot.conversations import ConversationOptions


class NaturalChannelTests(unittest.TestCase):
    def source(self, **changes):
        source = SourceSummary('isolated','sim-pond-1','simulator','OK',
            '2026-11-06T00:00:00+00:00','2026-11-06T00:00:01+00:00',
            '2026-11-06T00:00:02+00:00','valid','fresh','online',
            (SourceMetric('temperature_c',26.5,'°C','valid'),SourceMetric('ph',7.5,'','valid'),
             SourceMetric('dissolved_oxygen_mg_l',6.2,'mg/L','valid')),True)
        return replace(source, **changes)

    def answer(self, text, source=None):
        return HybridResult(True,None,source,text,'revision',branch='water' if source else 'general',
            model_requests=2 if source else 1,tool_executions=1 if source else 0)

    def test_general_concepts_numbers_and_denials_are_not_old_keyword_gate(self):
        for text in ('溶解氧是水中溶解的氧气，增氧有助于改善氧气供应。',
                     '例如水温20°C只是解释用的假设值，不是现场读数。',
                     '单凭聊天不能确诊，请结合地区和季节咨询专业人员。',
                     '这里只是一般知识，并不能确认当前鱼塘状况。',
                     '我没有查询当前水质，不能确认当前水质正常。',
                     '你是想问当前水质正常吗？还是想了解一般判断方法？',
                     '当前水质是否正常还需要查询。', '我没有读取现场。',
                     '溶解氧通常为解释用的6mg/L示例，不代表当前数据。',
                     '如果当前水质正常，还应继续定期监测。',
                     '假设当前溶解氧为6mg/L，这只是举例。',
                     '若当前水质正常，也不能据此保证长期适养。'):
            with self.subTest(text=text):
                result=present(self.answer(text))
                self.assertTrue(result.allowed)
                self.assertIn(text,result.text)
                self.assertIn('本轮未查询现场数据',result.text)
                self.assertFalse(result.general_fact_verifier)

    def test_no_tool_explicit_live_assertions_and_fake_operations_refused(self):
        for text in ('我已经查询现场水质。','当前溶解氧为6.2 mg/L。',
                     '你的鱼塘水质正常。','已关闭增氧设备。','I have checked current pond.',
                     '我未查询，但我已经确认当前水质正常。'):
            with self.subTest(text=text):
                result=present(self.answer(text))
                self.assertFalse(result.allowed)
                self.assertFalse(result.history_allowed)
                self.assertNotIn(text,result.text)

    def test_natural_water_keeps_answer_and_receipt_source_not_fixed_plan(self):
        text='本窗口溶解氧6.2 mg/L，暂未看到低氧规则命中。可以继续关注后续变化。'
        result=present(self.answer(text,self.source()))
        self.assertTrue(result.allowed)
        self.assertIn(text,result.text)
        self.assertIn('未逐句核验',result.text)
        self.assertIn('SIMULATOR',result.text)
        self.assertIn('2026-11-06 08:00:00',result.text)
        self.assertIn('北京时间 UTC+08',result.text)
        self.assertIn('有效/新鲜/在线',result.text)
        self.assertNotIn('已校验',result.text)

    def test_partial_stale_offline_and_hit_are_authoritative_even_short_model_text(self):
        source=self.source(quality='partial',freshness='stale',connectivity='offline',current_evidence_usable=False,
            metrics=(SourceMetric('temperature_c',26.5,'°C','valid'),SourceMetric('ph',None,'','missing'),
                     SourceMetric('dissolved_oxygen_mg_l',2.2,'mg/L','valid')),
            rule_hits=(SourceRule('OXYGEN_CRITICAL_LOW','critical','本轮可信严重规则命中'),))
        result=present(self.answer('留存溶解氧较低，请先核对新的观测。',source))
        self.assertTrue(result.allowed)
        for value in ('过期','离线','缺测','不能完整确认','严重','本轮可信严重规则命中'):
            self.assertIn(value,result.text)
        conflict=present(self.answer('当前水质全部正常。',source))
        self.assertFalse(conflict.allowed)
        self.assertTrue(conflict.facts_only)
        self.assertNotIn('全部正常',conflict.text)

    def test_no_data_unknown_source_preserved(self):
        source=self.source(status='NO_DATA',observed_at=None,received_at=None,quality='missing',
            freshness='unknown',connectivity='never_received',current_evidence_usable=False,
            metrics=tuple(replace(v,value=None,quality='missing') for v in self.source().metrics))
        result=present(self.answer('目前缺少观测，建议先核对设备上报。',source))
        self.assertIn('尚无观测',result.text)
        self.assertIn('观测 未知',result.text)
        self.assertIn('缺测/未知/尚未接收',result.text)

    def test_excess_text_does_not_truncate_provenance_or_release_raw_json(self):
        for text in ('字'*3000,'{"kind":"general","text":"hello"}','```unsafe```','bad\x00text'):
            general=present(self.answer(text))
            self.assertFalse(general.allowed)
            water=present(self.answer(text,self.source()))
            self.assertFalse(water.allowed)
            self.assertTrue(water.facts_only)
            self.assertIn('SIMULATOR',water.text)
            self.assertLessEqual(len(water.text),MAX_REPLY_CHARS)

    def test_continuous_budget_range_does_not_change_legacy_budget(self):
        for value in (1,512,2048,4096):
            self.assertEqual(ContinuousChannelBudget(value).max_output_tokens,value)
        for value in (0,4097,True,1.0,'2048'):
            with self.assertRaises(GatewayError):ContinuousChannelBudget(value)
        with self.assertRaises(GatewayError):ChannelBudget(4096)

    def test_scope_binds_plain_prompt_token_and_independent_consent(self):
        options=ConversationOptions(trigger_mode='mention_ai',memory_enabled=True)
        scope=prepared_scope(options,4096)
        self.assertEqual(scope['runtime']['prompt_id'],PROMPT_ID)
        self.assertIn('不要求JSON',INSTRUCTION)
        self.assertEqual(scope['execution']['max_output_tokens'],4096)
        self.assertEqual(scope['run_limits']['turn_timeout_s'],90)
        self.assertFalse(scope['run_limits']['cumulative_turn_stop'])
        self.assertNotEqual(scope,prepared_scope(options,2048))
        record=preparation_record(scope)
        self.assertEqual(record['status'],'candidate')
        self.assertIsNone(record['qualification_id'])
        self.assertFalse(record['old_approvals_accepted'])

    def test_completed_lease_release_is_not_reusable(self):
        from datetime import datetime, timezone
        authority=LeaseAuthority(lambda _:None)
        lease=authority._issue(approval_id='lease',sequence=1,scope_sha256='a'*64,bindings_sha256='b'*64,
            expires_at=datetime.now(timezone.utc),instance_id='i',device_id='d',app_id='a',group_id='g',
            member_id='m',message_key='message')
        authority.validate(lease)
        authority.release(lease)
        authority.release(lease)
        self.assertEqual(len(authority._issued),0)
        with self.assertRaises(GatewayError):authority.validate(lease)
