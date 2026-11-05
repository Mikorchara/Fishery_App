"""Real SDK classes, synthetic SQLite, Fake QQ and memory HTTP only."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from apps.ai_service.channel_management_continuous import prepared_scope, preparation_record, PROMPT_ID
from apps.ai_service.runtime.release_contracts import _hash
from apps.qq_bot.conversations import ConversationOptions
from apps.qq_bot.management_cli import initialize_demo
from apps.qq_bot.management_config import ROOT, load_request
from apps.qq_bot.tests import test_management_live as legacy


class NaturalManagementIntegrationTests(unittest.TestCase):
    compose = legacy.ManagementLiveTests.compose
    receive = legacy.ManagementLiveTests.receive
    ask = legacy.ManagementLiveTests.ask

    def setUp(self):
        temp=TemporaryDirectory(dir=ROOT/'outputs/test-tmp')
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.http=[];self.started=threading.Event();self.mode='general'
        self.general_text='溶解氧是水中溶解的氧气；例如20°C仅为概念解释，不代表现场。'
        self.path=initialize_demo(self.root/'instance',self.root/'config',app_id='123456789',
            group_id='group-a',members=('member-a','member-b'),enable=True)
        value=json.loads(self.path.read_text(encoding='utf8'))
        value.update(schema_version=2,ai_enabled=True,limits=dict(mode='continuous',seconds=None,max_turns=None,total_budget_cny=None))
        ai_path=self.path.parent/'ai.json'
        ai=json.loads(ai_path.read_text(encoding='utf8'))
        ai['schema_version']=2;ai['budget']['max_output_tokens']=4096
        ai_path.write_text(json.dumps(ai),encoding='utf8')
        options=ConversationOptions(trigger_mode='mention_ai',memory_enabled=True)
        scope=prepared_scope(options,4096)
        (self.path.parent/'scope.json').write_text(json.dumps(preparation_record(scope)),encoding='utf8')
        value['scope_sha256']=_hash(scope)
        self.path.write_text(json.dumps(value),encoding='utf8')
        self.request=load_request(self.path)
        self.outcomes=['ACCEPTED']*12;self.posts=[];self.seq=0
        self.addCleanup(patch.stopall)
        for target in ('socket.socket.connect','socket.getaddrinfo'):
            patch(target,side_effect=AssertionError('no real network')).start()
        from apps.ai_backend.tests import test_execution
        test_execution.ExecutionTests.setUp(self)
        from apps.ai_backend.credentials import CredentialStore
        original=CredentialStore.resolve
        def memory_only(store,*args,**kwargs):
            if store.private_location is not None or store.project_env_path is not None or type(store._process_env) is not dict:
                raise AssertionError('no real credentials')
            return original(store,*args,**kwargs)
        patch.object(CredentialStore,'resolve',memory_only).start()

    def factory(self,runtime,remaining):
        async def model(request):
            body=json.loads(request.content);self.http.append(body)
            tool=next((m for m in body['messages'] if m['role']=='tool'),None)
            if self.mode=='water' and tool is None:
                message=dict(role='assistant',content=None,tool_calls=[dict(id='memory-water',type='function',
                    function=dict(name='get_current_water_quality',arguments='{}'))])
                finish='tool_calls'
            else:
                text=self.general_text
                if tool is not None:
                    payload=json.loads(tool['content'])
                    value=payload['water_quality']['dissolved_oxygen_mg_l']
                    text=f'本次窗口溶解氧为{value} mg/L。可以继续关注后续观测变化。'
                message=dict(role='assistant',content=text);finish='stop'
            return httpx.Response(200,json=dict(id='memory',object='chat.completion',created=0,model=runtime.model,
                choices=[dict(index=0,message=message,finish_reason=finish)],
                usage=dict(prompt_tokens=30,completion_tokens=20,total_tokens=50)))
        return AsyncOpenAI(api_key='fictional',base_url=runtime.base_url,max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(model),trust_env=False,follow_redirects=False))

    def test_natural_mixed_history_4096_sdk_source_delivery_and_cleanup(self):
        self.compose()
        before=(self.root/'instance/monitoring.sqlite3').read_bytes()
        for mode in ('general','general','water','water','general'):
            self.mode=mode
            done=self.ask('现在水质怎样？' if mode=='water' else '一般解释溶解氧')
            self.assertEqual(done.get('history_code'),'HISTORY_COMMITTED',done)
            self.assertEqual(done['state'],'DELIVERED')
        self.assertEqual((len(self.http),len(self.posts)),(7,5))
        self.assertTrue(all(body['max_tokens']==4096 for body in self.http))
        self.assertIn('不要求JSON',self.http[0]['messages'][0]['content'])
        self.assertIn(self.general_text,self.posts[0]['content'])
        self.assertNotIn('未通过展示检查',self.posts[0]['content'])
        self.assertIn('本轮未查询现场数据',self.posts[0]['content'])
        self.assertIn('本次窗口溶解氧为',self.posts[2]['content'])
        self.assertIn('系统来源：SIMULATOR',self.posts[2]['content'])
        self.assertIn('未逐句核验',self.posts[2]['content'])
        self.assertEqual(self.host.store.counts()['turns'],5)
        self.assertEqual(len(self.host.sessions),0)
        self.assertEqual(len(self.host.ledger.authority._issued),0)
        self.assertEqual(before,(self.root/'instance/monitoring.sqlite3').read_bytes())
        for turn in self.host.turns:
            self.assertTrue(turn['model_text_displayed'])
            self.assertFalse(turn['model_text_verified'])
            self.assertEqual(turn['sdk_resources']['state'],'CLOSED')
            self.assertTrue(turn['sdk_resources']['thread_exited'])

    def test_no_tool_false_current_claim_is_safe_reply_without_success_history(self):
        self.compose()
        self.general_text='我已经查询现场水质，当前水质正常。'
        done=self.ask('你确认数据正常吗？')
        self.assertNotEqual(done.get('history_code'),'HISTORY_COMMITTED')
        self.assertEqual(len(self.http),1)
        self.assertEqual(len(self.posts),1)
        self.assertNotIn(self.general_text,self.posts[0]['content'])
        self.assertEqual(self.host.store.counts()['turns'],0)

    def test_unknown_delivery_never_repeats_model_or_commits_history(self):
        self.compose();self.outcomes[0]='UNKNOWN'
        done=self.ask()
        self.assertEqual(done['state'],'DELIVERY_UNKNOWN',done)
        self.assertEqual((len(self.http),len(self.posts)),(1,1))
        self.assertEqual(self.host.store.counts()['turns'],0)
        self.assertEqual(len(self.host.ledger.authority._issued),0)
