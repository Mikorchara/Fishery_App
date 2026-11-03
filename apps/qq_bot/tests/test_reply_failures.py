"""Management 2048-token contract and safe error notices; memory HTTP only."""
from decimal import Decimal
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_service.channel_trial import QwenTrialSession,cost_reservation
from apps.ai_service.management_channel_budget import CHANNEL_BUDGET,OUTPUT_TOKENS,reservation_per_turn
from apps.qq_bot.management_config import load_request,check_request
from apps.qq_bot.run_consent import RunLimits
from apps.qq_bot.tests import test_management_live as live_fixture


class ReplyFailureTests(unittest.TestCase):
    setUp=live_fixture.ManagementLiveTests.setUp
    compose=live_fixture.ManagementLiveTests.compose
    ask=live_fixture.ManagementLiveTests.ask
    receive=live_fixture.ManagementLiveTests.receive

    def factory(self,runtime,remaining):
        if self.mode not in ('truncated','long_usage','invalid_usage'):
            return live_fixture.ManagementLiveTests.factory(self,runtime,remaining)
        async def model(request):
            body=json.loads(request.content);self.http.append(body)
            if self.mode=='truncated' and not any(m['role']=='tool' for m in body['messages']):
                message=dict(role='assistant',content=None,tool_calls=[dict(id='call-test',type='function',
                    function=dict(name='get_current_water_quality',arguments='{}'))]);reason='tool_calls';tokens=15
            else:
                message=dict(role='assistant',content=json.dumps(dict(contract='qq-hybrid-reply@2',kind='general',text='溶解氧是水中溶解的氧气。')))
                reason='length' if self.mode=='truncated' else 'stop'
                tokens=2048 if self.mode=='truncated' else 2049 if self.mode=='invalid_usage' else 700
            return httpx.Response(200,json=dict(id='fake',object='chat.completion',created=0,model=runtime.model,
                choices=[dict(index=0,message=message,finish_reason=reason)],
                usage=dict(prompt_tokens=20,completion_tokens=tokens,total_tokens=20+tokens)))
        return AsyncOpenAI(api_key='fictional-only',base_url=runtime.base_url,max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(model),trust_env=False,follow_redirects=False))

    def test_management_scope_2048_budget_and_old_defaults_remain_independent(self):
        _,summary=check_request(self.path,offline=True)
        self.assertEqual(summary['output_tokens_per_request'],2048)
        self.assertEqual(summary['reservation_per_turn_cny'],'1.611060')
        self.assertEqual(summary['limits']['total_budget_cny'],'8.06')
        self.assertEqual(cost_reservation(),Decimal('1.602765'))
        self.assertEqual(QwenTrialSession.output_token_limit,512)
        self.compose();self.mode='long_usage';done=self.ask()
        self.assertEqual(done['state'],'DELIVERED');self.assertEqual(done['history_code'],'HISTORY_COMMITTED')
        self.assertEqual(self.http[0]['max_tokens'],2048)
        self.assertEqual(self.host.turns[0]['usage']['output_tokens'],700)
        self.assertEqual(self.host.ledger.report()['reserved_cost_cny'],'1.611060')
        self.assertEqual(self.host.scope['execution']['max_output_tokens'],2048)
        self.assertEqual(self.host.scope['cost']['output_tokens_per_request'],2048)
        self.assertEqual(self.host.scope['runtime']['prompt_id'],'QQ_MANAGEMENT_HYBRID_DIALOGUE@4')

    def test_insufficient_legacy_run_budget_and_wrong_channel_config_refused(self):
        value=json.loads(self.path.read_text());value['limits']['total_budget_cny']='8.02'
        other=self.root/'insufficient.json';other.write_text(json.dumps(value))
        with self.assertRaisesRegex(Exception,'RUN_BUDGET_INSUFFICIENT'):load_request(other)
        self.assertEqual(self.http,[])

    def test_invalid_arguments_one_notice_zero_tool_reads_and_no_success_history(self):
        self.compose(failure_feedback=True);self.mode='wrong_device'
        replay={};original=self.router.receive
        def capture(raw,**kwargs):
            replay.update(raw=raw,kwargs=kwargs);return original(raw,**kwargs)
        with patch.object(self.host.monitoring,'capture_water',side_effect=AssertionError('no handler')),\
             patch.object(self.router,'receive',capture):
            code,task=self.receive('查询水质',message_id='same-msg');self.assertEqual(code,'AI_ADMITTED')
            done=self.scheduler.wait(task,95)
        self.assertEqual(done['state'],'FAILED');self.assertEqual(done['code'],'INVALID_TOOL_ARGUMENTS')
        self.assertFalse(done['api_accepted']);self.assertTrue(done['failure_notice']['api_accepted'])
        self.assertEqual((len(self.http),len(self.posts),self.host.store.counts()['turns']),(1,1,0))
        self.assertIn('工具参数',self.posts[0]['content'])
        self.assertEqual(original(replay['raw'],**replay['kwargs'])[0],'DUPLICATE')
        self.assertEqual(self.host.ledger.report()['consumed_turns'],1)
        record=json.loads((self.host.directory/'turn-1.failure-notice.json').read_text())
        self.assertFalse(record['successful_ai_reply']);self.assertFalse(record['history_committed'])
        statuses=self.scheduler.take_statuses();self.assertEqual(statuses[0]['reason'],'INVALID_TOOL_ARGUMENTS')
        self.assertNotIn('查询水质',json.dumps(statuses,ensure_ascii=False))

    def test_truncation_two_requests_error_notice_not_incomplete_answer(self):
        self.compose(failure_feedback=True);self.mode='truncated';done=self.ask('查询水质')
        self.assertEqual(done['code'],'ASSISTANT_RESPONSE_TRUNCATED');self.assertEqual(done['state'],'FAILED')
        self.assertTrue(done['failure_notice']['api_accepted']);self.assertFalse(done['api_accepted'])
        self.assertEqual(len(self.http),2);self.assertTrue(all(b['max_tokens']==2048 for b in self.http))
        self.assertEqual(len(self.posts),1);self.assertIn('被截断',self.posts[0]['content'])
        self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertFalse(self.host.turns[0]['verified']);self.assertEqual(done['sdk_resources']['state'],'CLOSED')

    def test_unknown_failure_notice_never_retries_or_commits_history(self):
        self.compose(failure_feedback=True);self.mode='wrong_device';self.outcomes[0]='UNKNOWN'
        done=self.ask();self.assertEqual(done['state'],'FAILED')
        self.assertEqual(done['failure_notice']['status'],'DELIVERY_UNKNOWN')
        self.assertFalse(done['failure_notice']['api_accepted'])
        self.assertEqual((len(self.http),len(self.posts),self.host.store.counts()['turns']),(1,1,0))
        self.assertEqual(self.host.ledger.report()['consumed_turns'],1)

    def test_failure_notice_rechecks_revoke_before_send(self):
        from dataclasses import replace
        self.compose(failure_feedback=True);self.mode='wrong_device'
        entered,release=threading.Event(),threading.Event();original=self.scheduler.delivery.deliver_failure
        def blocked(*args):
            entered.set();self.assertTrue(release.wait(8));return original(*args)
        with patch.object(self.scheduler.delivery,'deliver_failure',blocked):
            _,task=self.receive();self.assertTrue(entered.wait(8))
            self.coordinator.reconfigure(replace(self.coordinator.config,enabled=False));release.set()
            done=self.scheduler.wait(task,15)
        self.assertFalse(done.get('failure_notice',{}).get('api_accepted'))
        self.assertEqual(self.posts,[]);self.assertEqual(self.host.store.counts()['turns'],0)

    def test_failure_checkpoint_error_halts_without_repeat(self):
        from apps.qq_bot import session_run
        self.compose(failure_feedback=True);self.mode='wrong_device';original=session_run.write_new
        def fail(path,value):
            if path.name.endswith('.failure-notice.json'):raise OSError('synthetic')
            return original(path,value)
        with patch.object(session_run,'write_new',fail):done=self.ask()
        self.assertEqual(done['report_error'],'RUN_CHECKPOINT_FAILED')
        self.assertEqual(self.host.ledger.report()['state'],'HALTED')
        self.assertEqual((len(self.http),len(self.posts)),(1,1))
        self.assertNotEqual(self.receive()[0],'AI_ADMITTED')

    def test_usage_above_2048_is_rejected_and_never_published(self):
        self.compose(failure_feedback=True);self.mode='invalid_usage';done=self.ask()
        self.assertEqual(done['state'],'FAILED');self.assertEqual(self.posts,[])
        self.assertEqual(self.host.store.counts()['turns'],0)

    def test_five_turns_reserve_new_amount_without_refund_or_extra_requests(self):
        self.compose()
        for _ in range(5):self.assertEqual(self.ask()['state'],'DELIVERED')
        self.assertEqual(self.host.ledger.report()['reserved_cost_cny'],'8.055300')
        self.assertNotEqual(self.receive()[0],'AI_ADMITTED');self.assertEqual(len(self.http),5)
