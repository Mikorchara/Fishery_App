"""QQ Web Agent: real SDK classes with memory HTTP and new SQLite."""
import json
import unittest
import httpx
from openai import AsyncOpenAI

from apps.ai_service.channel_management_agent import TOOLS, prepared_scope, preparation_record
from apps.ai_service.runtime.release_contracts import _hash
from apps.qq_bot.conversations import ConversationOptions
from apps.qq_bot.management_config import load_request
from apps.qq_bot.tests import test_natural_management_live as previous


class ManagementAgentTests(unittest.TestCase):
    compose=previous.NaturalManagementIntegrationTests.compose
    receive=previous.NaturalManagementIntegrationTests.receive
    ask=previous.NaturalManagementIntegrationTests.ask

    def setUp(self):
        previous.NaturalManagementIntegrationTests.setUp(self)
        value=json.loads(self.path.read_text(encoding='utf8'))
        value.update(schema_version=3,agent_mode='web')
        ai_path=self.path.parent/'ai.json'
        ai=json.loads(ai_path.read_text(encoding='utf8'))
        ai['schema_version']=3
        ai['grants'][0]['tools']=list(TOOLS)
        ai_path.write_text(json.dumps(ai),encoding='utf8')
        policy=self.path.parent/'policy/management_assistant_policy.json'
        policy.write_text(json.dumps(dict(schema_version=1,generation=1,selected_tools=list(TOOLS))),encoding='utf8')
        scope=prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True),4096)
        (self.path.parent/'scope.json').write_text(json.dumps(preparation_record(scope)),encoding='utf8')
        value['scope_sha256']=_hash(scope)
        self.path.write_text(json.dumps(value),encoding='utf8')
        self.request=load_request(self.path)
        from apps.knowledge.repository import KnowledgeRepository
        from apps.knowledge.service import KnowledgeContentService
        knowledge=KnowledgeContentService(KnowledgeRepository(self.root/'instance/knowledge.sqlite3',require_existing=True))
        knowledge.create(dict(title='溶解氧背景资料',category='water_quality',body='溶解氧是水中溶解的氧气，为鱼类呼吸提供条件。增氧可补充氧气。'))
        self.plan=()
        self.finish_reason='stop'
        self.general_text='水温20°C只是一般解释举例，不是现场读数。'

    def factory(self,runtime,remaining):
        async def model(request):
            body=json.loads(request.content);self.http.append(body)
            observed=[m for m in body['messages'] if m['role']=='tool']
            if len(observed)<len(self.plan):
                name,arguments=self.plan[len(observed)]
                message=dict(role='assistant',content=None,tool_calls=[dict(id='step-'+str(len(observed)),type='function',
                    function=dict(name=name,arguments=json.dumps(arguments)))])
                finish='tool_calls'
            else:
                message=dict(role='assistant',content=self.general_text)
                finish=self.finish_reason
            return httpx.Response(200,json=dict(id='memory',object='chat.completion',created=0,model=runtime.model,
                choices=[dict(index=0,message=message,finish_reason=finish)],
                usage=dict(prompt_tokens=40,completion_tokens=25,total_tokens=65)))
        return AsyncOpenAI(api_key='fictional',base_url=runtime.base_url,max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(model),trust_env=False,follow_redirects=False))

    def test_all_five_tools_use_existing_handlers_receipts_and_natural_history(self):
        self.compose()
        before={name:(self.root/'instance'/name).read_bytes() for name in ('knowledge.sqlite3','monitoring.sqlite3')}
        cases=(('get_current_water_quality',{},'SIMULATOR'),
               ('get_water_quality_history',{'lookback_minutes':10},'历史窗口'),
               ('search_fishery_knowledge',{'query':'溶解氧'},'项目知识'),
               ('score_current_water_quality',{},'实验评分'),
               ('get_active_events',{},'事件查询'))
        for name,args,note in cases:
            self.plan=((name,args),)
            self.general_text='这是根据本轮已取得资料给出的简洁答复。'
            done=self.ask('请使用本轮资料回答')
            self.assertEqual(done.get('history_code'),'HISTORY_COMMITTED',done)
            self.assertIn(note,self.posts[-1]['content'])
            self.assertEqual(self.host.turns[-1]['tool_executions'],1)
            self.assertEqual(self.host.turns[-1]['source_kinds'],[name])
        self.assertEqual(len(self.http),10)
        self.assertEqual(len(self.posts),5)
        for name,bytes_before in before.items():self.assertEqual((self.root/'instance'/name).read_bytes(),bytes_before)
        for body in self.http:
            self.assertEqual(body['max_tokens'],4096)
            self.assertEqual([d['function']['name'] for d in body['tools']],list(TOOLS))

    def test_current_event_question_requires_new_evidence(self):
        self.compose(failure_feedback=True)
        self.general_text='我确认没有任何异常。'
        done=self.ask('请问现在发生什么事件了吗？')
        self.assertEqual(done['code'],'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
        self.assertTrue(done['failure_notice']['api_accepted'])
        self.assertIn('未取得事件查询结果',self.posts[-1]['content'])
        self.assertEqual(self.host.store.counts()['turns'],0)

    def test_device_mode_board_is_bound_to_approval_and_query(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from apps.monitoring.repository import MonitoringRepository
        from apps.monitoring.tests.test_device_events import DeviceEventTests
        from apps.qq_bot.contracts import BotError
        now=datetime.now(timezone.utc)
        fixture=SimpleNamespace(now=now)
        fixture.report=lambda *a, **kw:DeviceEventTests.report(fixture,*a,**kw)
        repo=MonitoringRepository(self.root/'instance/monitoring.sqlite3',require_existing=True)
        for device in ('board-1','other-board'):
            report=DeviceEventTests.peak_report(fixture,1,appearance=True)
            repo.import_device_report({**report,'device_id':device},received_at=now,inbox_cursor=1,now=now)
        self.compose(event_board_device_id='board-1')
        self.assertEqual(self.host.plan()['agent_event_board_device_id'],'board-1')
        with self.assertRaisesRegex(BotError,'MONITORING_DEVICE_NOT_APPROVED'):
            self.host.monitoring.active_event_snapshot('sim-pond-1',board_device_id='other-board')
        self.plan=(('get_active_events',{}),)
        self.general_text='设备出现外观检测信号，需要人工核查。'
        done=self.ask('请问现在发生什么事件了吗？')
        self.assertEqual(done['history_code'],'HISTORY_COMMITTED')
        result=json.loads(next(row['content'] for row in self.http[-1]['messages'] if row['role']=='tool'))
        self.assertEqual([source['device_id'] for source in result['sources']],['sim-pond-1','board-1'])
        self.assertTrue(any(item['code']=='DEVICE_REPORT_APPEARANCE' for item in result['items']))
        self.assertIn('设备报告',self.posts[-1]['content'])
        self.assertNotIn('other-board',self.posts[-1]['content'])
        self.host._event_board_device_id='other-board'
        with self.assertRaisesRegex(BotError,'AGENT_EVENT_BOARD_NOT_APPROVED'):
            self.host.check()

    def test_current_and_history_run_original_two_round_three_request_loop(self):
        self.compose()
        self.plan=(('get_current_water_quality',{}),('get_water_quality_history',{'lookback_minutes':30}))
        self.general_text='当前窗口与历史窗口来自不同时间范围，应分别理解。'
        done=self.ask('请对比当前与最近30分钟')
        self.assertEqual(done.get('history_code'),'HISTORY_COMMITTED',done)
        self.assertEqual(len(self.http),3)
        self.assertIn('历史窗口',self.posts[-1]['content'])
        self.assertIn('SIMULATOR',self.posts[-1]['content'])
        report=self.host.turns[-1]
        self.assertEqual(report['tool_executions'],2)
        self.assertEqual(report['model_http_requests'],3)
        self.assertEqual(report['sdk_resources']['state'],'CLOSED')
        self.assertTrue(report['sdk_resources']['thread_exited'])
        self.assertEqual(len(self.host.ledger.authority._issued),0)

    def test_general_one_request_and_contextual_knowledge_followup(self):
        self.compose()
        first=self.ask('水温为什么重要？')
        self.assertEqual(first.get('history_code'),'HISTORY_COMMITTED',first)
        self.assertEqual(len(self.http),1)
        self.assertIn(self.general_text,self.posts[-1]['content'])
        self.plan=(('search_fishery_knowledge',{'query':'溶解氧'}),)
        self.general_text='项目资料将溶解氧解释为水中溶解的氧气。'
        second=self.ask('那项目资料怎么解释溶解氧？')
        self.assertEqual(second.get('history_code'),'HISTORY_COMMITTED',second)
        self.assertEqual(len(self.http),3)
        self.assertIn('项目知识',self.posts[-1]['content'])
        self.assertIn('历史对话',str(self.http[1]['messages']))
        self.assertNotIn('系统来源：SIMULATOR',self.posts[-1]['content'])

    def test_false_current_execution_with_knowledge_only_is_not_site_evidence(self):
        self.compose()
        self.plan=(('search_fishery_knowledge',{'query':'溶解氧'}),)
        self.general_text='我已查询当前水质，现场一切正常。'
        done=self.ask('查询项目资料')
        self.assertNotEqual(done.get('history_code'),'HISTORY_COMMITTED')
        self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertIn('没有取得现场查询依据',self.posts[-1]['content'])
        self.assertEqual(len(self.http),2)

    def test_invalid_write_tool_and_history_cross_device_are_not_executed(self):
        self.compose()
        for name,args in (('delete_event',{}),('get_water_quality_history',{'lookback_minutes':10,'device_id':'other'})):
            self.plan=((name,args),)
            before=len(self.http)
            done=self.ask('test capability boundary')
            self.assertEqual(done['state'],'FAILED',done)
            self.assertEqual(len(self.http)-before,1)
        self.assertEqual(self.host.store.counts()['turns'],0)

    def test_bounded_model_truncation_gets_one_failure_notice_without_partial_history(self):
        self.compose(failure_feedback=True)
        self.finish_reason='length'
        self.general_text='这是一段被截断的正文，不应发送'
        done=self.ask('请解释当前季节的注意事项')
        self.assertEqual(done['state'],'FAILED',done)
        self.assertEqual(done['code'],'MODEL_RESPONSE_TRUNCATED')
        self.assertTrue(done['failure_notice']['api_accepted'])
        self.assertEqual((len(self.http),len(self.posts)),(1,1))
        self.assertIn('达到输出Token上限',self.posts[-1]['content'])
        self.assertNotIn(self.general_text,self.posts[-1]['content'])
        self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertEqual(self.host.turns[-1]['sdk_resources']['state'],'CLOSED')
        self.finish_reason='stop'
        self.general_text='建议结合地区、品种和近期环境具体判断。'
        next_turn=self.ask('怎样收集判断资料？')
        self.assertEqual(next_turn.get('history_code'),'HISTORY_COMMITTED',next_turn)
        self.assertEqual((len(self.http),len(self.posts)),(2,2))
