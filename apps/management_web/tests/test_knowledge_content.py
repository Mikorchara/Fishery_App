"""Managed content HTTP and actual Knowledge Tool over a shared isolated store."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from apps.ai_backend.tests.support import FakeSDK,sdk_tool,sdk_final,tool_chunks,final_chunks
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
import apps.ai_service.tests.test_unified_tools as fixture
from apps.ai_service.service import ManagementAssistantService
from apps.knowledge.tests.support import seed
from apps.knowledge.repository import KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService,CONTENT_SOURCE
from apps.management_web.ai_adapter import ManagementAssistant
from apps.management_web.app import create_app

VALUE={'title':'蓝莓浮岛','category':'用户试验资料','body':'蓝莓浮岛的银鳞鱼采用独立观察记录。这是用户背景知识，不是当前监测事实。'}
WATER,KNOWLEDGE,HISTORY=fixture.WATER,fixture.KNOWLEDGE,fixture.HISTORY


class KnowledgeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.UnifiedToolsTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;seed(f.root/'knowledge.sqlite3');self.old=f.backend
        self.install_content(KnowledgeContentService(KnowledgeRepository(f.root/'knowledge.sqlite3')))

    def install_content(self, content):
        f=self.fixture
        self.content=content
        old=self.old
        f.backend=ManagementAssistantService(f.monitoring,credentials=old.credentials,traces=old.traces,
            policy_directory=old.policy_store.directory,knowledge=self.content,
            gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=f.sdk.factory),
            execution_config=old._execution_config,streaming_config=old._streaming_config,unified_config=old._unified_config)
        f.web=ManagementAssistant(f.backend)
        self.app=create_app(data_service=f.monitoring,ai=f.web,knowledge_service=self.content)
        f.client=self.app.test_client();f.headers={'X-Management-AI':f.web.browser_token}
        self.client=f.client
        self.token=self.client.get('/api/knowledge').get_json()['write_token']
        self.headers={'X-Management-Knowledge':self.token}

    def create(self):
        response=self.client.post('/api/knowledge',json=VALUE,headers=self.headers)
        self.assertEqual(response.status_code,201,response.get_json());return response.get_json()

    def test_actual_http_crud_search_versions_filters_and_restore(self):
        item=self.create();url='/api/knowledge/'+item['id']
        self.assertEqual(self.client.get(url).get_json()['body'],VALUE['body'])
        result=self.client.post('/api/knowledge/search',json={'query':'蓝莓浮岛'},headers=self.headers).get_json()
        hit=next(h for h in result['evidence'] if h['id']==item['id']);self.assertEqual(hit['source_version'],'1')
        edited=self.client.patch(url,json={**VALUE,'title':'银鳞红珊瑚','version':1,'body':'银鳞红珊瑚是新的养殖笔记内容。'},headers=self.headers).get_json()
        self.assertEqual(edited['version'],2)
        conflict=self.client.patch(url,json={**VALUE,'version':1},headers=self.headers)
        self.assertEqual(conflict.status_code,409)
        for status in ('DISABLED','DELETED','ACTIVE'):
            edited=self.client.post(url+'/status',json={'version':edited['version'],'status':status},headers=self.headers).get_json()
            hits=self.client.post('/api/knowledge/search',json={'query':'银鳞红珊瑚'},headers=self.headers).get_json()['evidence']
            self.assertEqual(any(h['id']==item['id'] for h in hits),status=='ACTIVE')
        rows=self.client.get('/api/knowledge?q=银鳞红珊瑚&category=用户试验资料').get_json()['items']
        self.assertEqual(len(rows),1);self.assertNotIn('body',rows[0])
        self.assertNotIn(str(self.fixture.root),json.dumps(rows))

    def test_content_without_ai_and_restart_through_actual_startup_factory(self):
        from apps.management_web.__main__ import knowledge_content
        seed(self.fixture.root/'apps/knowledge_data/knowledge.sqlite3')
        service=knowledge_content(self.fixture.root)
        app=create_app(knowledge_service=service);client=app.test_client()
        token=client.get('/api/knowledge').get_json()['write_token']
        item=client.post('/api/knowledge',json=VALUE,headers={'X-Management-Knowledge':token}).get_json()
        self.assertEqual(knowledge_content(self.fixture.root).get(item['id'])['body'],VALUE['body'])
        self.assertFalse(client.get('/api/ai/status').get_json()['connected'])
        self.assertEqual(client.post('/api/ai/messages',json={}).status_code,503)

    def test_host_origin_loopback_token_type_size_and_unknown_fields(self):
        for options in ({'headers':{}},{'headers':{'X-Management-Knowledge':'wrong'}},
                        {'headers':{**self.headers,'Origin':'http://evil.invalid'}},
                        {'headers':self.headers,'base_url':'http://evil.invalid'},
                        {'headers':self.headers,'environ_overrides':{'REMOTE_ADDR':'10.1.1.1'}}):
            self.assertEqual(self.client.post('/api/knowledge',json=VALUE,**options).status_code,403)
        self.assertEqual(self.client.get('/api/knowledge',environ_overrides={'REMOTE_ADDR':'10.1.1.1'}).status_code,403)
        for value in ({**VALUE,'id':'arbitrary'},{**VALUE,'body':'x'*6001},[] ):
            self.assertEqual(self.client.post('/api/knowledge',json=value,headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/knowledge',data='x'*33000,headers=self.headers).status_code,413)
        self.assertEqual(self.client.post('/api/knowledge',data='{"title":"a","title":"b"}',content_type='application/json',headers=self.headers).status_code,400)
        self.assertEqual(self.client.get('/api/knowledge/user-invalid').status_code,400)
        self.assertEqual(self.client.get('/api/knowledge?q='+'x'*129).status_code,400)
        self.assertFalse(self.fixture.sdk.bodies)

    def test_imported_builtins_editable_no_match_and_bounded_test_evidence(self):
        item=self.client.get('/api/knowledge').get_json()['items'][0]
        edited=self.client.patch('/api/knowledge/'+item['id'],json={**VALUE,'version':1},headers=self.headers)
        self.assertEqual(edited.status_code,200);self.assertEqual(edited.get_json()['original_source_id'],item['source_id'])
        created=self.client.post('/api/knowledge',json={**VALUE,'body':'蓝莓浮岛'*1400},headers=self.headers).get_json()
        result=self.client.post('/api/knowledge/search',json={'query':'蓝莓浮岛'},headers=self.headers).get_json()
        self.assertLessEqual(result['result_count'],3)
        self.assertTrue(all(len(h['text'])<=801 for h in result['evidence']))
        result=self.client.post('/api/knowledge/search',json={'query':'🛰🛰🛰'},headers=self.headers).get_json()
        self.assertEqual(result['status'],'NO_MATCH');self.assertEqual(result['evidence'],[])
        for value in ({'query':'x','top_k':10},{'query':True},{'query':'bad\nquery'}):
            self.assertEqual(self.client.post('/api/knowledge/search',json=value,headers=self.headers).status_code,400)

    def test_managed_scope_exact_identity_and_no_qualification_inheritance(self):
        f=self.fixture
        for key in ('normal_scope_json','streaming_scope_json'):
            old=json.loads(getattr(self.old._unified_config,key));new=json.loads(getattr(f.backend._unified_config,key))
            changed={name for name in old if old[name]!=new[name]}
            self.assertEqual(changed,{'data_bindings'})
            self.assertEqual(new['data_bindings']['knowledge_source'],CONTENT_SOURCE)
            self.assertEqual(new['runtime'],old['runtime']);self.assertEqual(new['budget'],old['budget'])
        for config in (f.backend._execution_config,f.backend._streaming_config):
            for entry in config.releases:
                self.assertIsNone(entry.runtime.qualification_id);self.assertIsNone(entry.runtime.validated_at)
        self.content.create(VALUE)
        current=f.envelope();self.assertNotEqual(current['revision'],self.old.bootstrap('pond-a')['presets'][0]['execution']['revision'])
        with self.assertRaisesRegex(ValueError,'AI_KNOWLEDGE_SOURCE_MISMATCH'):
            create_app(data_service=f.monitoring,ai=f.web,knowledge_service=KnowledgeContentService(KnowledgeRepository(f.root/'other.sqlite3')))

    def test_real_registry_executor_normal_streaming_content_source_and_commit(self):
        item=self.create();f=self.fixture
        arguments=json.dumps({'query':'蓝莓浮岛'},ensure_ascii=False)
        for streaming in (False,True):
            with self.subTest(streaming=streaming):
                plans=[tool_chunks(KNOWLEDGE,'k1',arguments),final_chunks()] if streaming else [
                    sdk_tool(KNOWLEDGE,'k1',arguments,f.profile.model),sdk_final(model=f.profile.model)]
                result=f.send((KNOWLEDGE,),streaming,plans=plans)
                self.assertTrue(result['successful_turn'],result)
                payload=json.loads(next(m['content'] for m in f.sdk.bodies[1]['messages'] if m['role']=='tool'))
                evidence=next(h for h in payload['evidence'] if h['id']==item['id'])
                self.assertEqual(evidence['source_version'],'1');self.assertEqual(evidence['source'],item['source_id'])
                receipt=f.captured[0].source_ledger.entries[0].receipt
                self.assertTrue(receipt.project_search_completed);self.assertTrue(receipt.has_project_evidence)
                self.assertFalse(receipt.observation_query_completed);self.assertFalse(receipt.history_query_completed)
                self.assertTrue(all(b['max_tokens']==(512 if streaming else 1024) for b in f.sdk.bodies))
                safe=json.dumps(result)+f.backend.traces.path.read_text(encoding='utf-8')
                self.assertNotIn(VALUE['body'],safe)
                self.assertTrue(all(c.closed and (not c.stream or c.stream.closed) for c in f.sdk.clients))

    def test_curated_web_uses_original_conditions_even_when_model_query_changes_them(self):
        from apps.knowledge.initial import initialize_curated_knowledge

        f = self.fixture
        path = f.root / 'curated.sqlite3'
        initialize_curated_knowledge(path)
        self.install_content(KnowledgeContentService(KnowledgeRepository(path, require_existing=True)))
        args = json.dumps({'query': '日本鳗鲡溶氧 6–7 mg/L 摄食'}, ensure_ascii=False)
        f.sdk = FakeSDK([
            sdk_tool(KNOWLEDGE, 'curated-search', args, f.profile.model),
            sdk_final('源文片段已核对。', model=f.profile.model),
        ], model=f.profile.model)
        original = '请查项目资料，日本鳗鲡溶解氧在 2.11 mg/L 的实验摄食率。'
        response = f.client.post('/api/ai/messages', headers=f.headers, json={**f.envelope(), 'question': original})
        self.assertTrue(response.get_json()['result']['successful_turn'], response.get_json())
        payload = json.loads(next(item['content'] for item in f.sdk.bodies[1]['messages'] if item['role'] == 'tool'))
        self.assertEqual(payload['status'], 'OK')
        self.assertTrue(any('2.11' in item['text'] and item['source'] == 'https://doi.org/10.2331/suisan.49.1335'
                            for item in payload['evidence']))
        self.assertFalse(any('6–7' in item['text'] for item in payload['evidence']))

    def use_curated_content(self):
        from apps.knowledge.initial import initialize_curated_knowledge

        path = self.fixture.root / 'curated-publication.sqlite3'
        initialize_curated_knowledge(path)
        self.install_content(KnowledgeContentService(
            KnowledgeRepository(path, require_existing=True, read_only=True)))

    def test_curated_numeric_reply_is_grounded_in_normal_and_streaming_web(self):
        self.use_curated_content()
        f = self.fixture
        unsupported = '实验摄食率为 95%，整个区间均如此。'
        rewritten = '日本鳗鲡溶解氧 2.11 mg/L 摄食'
        cases = (
            ('日本鳗鲡', '2.11 mg/L', None, 'OK', ('2.11 mg/L', '8.9%', '10.2331/suisan.49.1335')),
            ('日本鳗鲡', '1–3 mg/L', None, 'OK', ('2.11', '2.94', '8.9%', '12.8%', '不能据此推断整个区间')),
            ('日本鳗鲡', '6–7 mg/L', None, 'OK', ('6.27', '14.1%', '不能据此推断整个区间')),
            ('日本鳗鲡', '21.1% 饱和度', None, 'OK', ('21.1%', '3.76%', '10.2331/suisan.52.597')),
            ('日本鳗鲡', '9–10 mg/L', None, 'NO_MATCH', ('未找到',)),
            ('俄罗斯鲟', '2.11 mg/L', rewritten, 'NO_MATCH', ('未找到',)),
            ('日本鳗鲡', '2.11 mg/L·h', rewritten, 'NO_MATCH', ('未找到',)),
        )
        for streaming in (False, True):
            for species, concentration, tool_query, expected_status, expected_parts in cases:
                with self.subTest(streaming=streaming, species=species, concentration=concentration):
                    arguments = json.dumps({'query': tool_query or f'{species}溶解氧 {concentration} 摄食'})
                    plans = [tool_chunks(KNOWLEDGE, 'lookup', arguments), final_chunks(unsupported)] if streaming else [
                        sdk_tool(KNOWLEDGE, 'lookup', arguments, f.profile.model),
                        sdk_final(unsupported, model=f.profile.model),
                    ]
                    f.sdk = FakeSDK(plans, model=f.profile.model)
                    response = f.client.post('/api/ai/messages' + ('/stream' if streaming else ''),
                        headers=f.headers, json={**f.envelope(streaming), 'question':
                            f'请查项目资料，{species}在溶解氧 {concentration} 时的实验摄食率是多少？'})
                    self.assertEqual(response.status_code, 200, response.get_json(silent=True))
                    if streaming:
                        events = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines()
                                  if line.startswith('data: ')]
                        self.assertNotIn('preview', [event['kind'] for event in events])
                        self.assertEqual(events[-1]['kind'], 'final', events[-1])
                        result = events[-1]['result']
                    else:
                        result = response.get_json()['result']
                    response.close()
                    self.assertTrue(result['successful_turn'], result)
                    self.assertEqual(len(f.sdk.bodies), 2)
                    payload = json.loads(next(message['content'] for message in f.sdk.bodies[-1]['messages']
                                              if message['role'] == 'tool'))
                    self.assertEqual(payload['status'], expected_status)
                    reply = result['final_text']
                    for part in expected_parts:
                        self.assertIn(part, reply)
                    self.assertNotIn('95%', reply)
                    if expected_status == 'NO_MATCH':
                        self.assertNotIn('%', reply)
                        self.assertNotIn('10.2331/', reply)

    def test_explicit_project_lookup_needs_a_completed_search(self):
        self.use_curated_content()
        f = self.fixture
        unsupported = '我已经检索了相应的项目资料。'
        prefixes = ('请查项目资料', '请从项目资料里查一下', '请帮我查项目资料', '请参考项目资料')
        for streaming in (False, True):
            for prefix in prefixes:
                with self.subTest(streaming=streaming, prefix=prefix):
                    plan = final_chunks(unsupported) if streaming else sdk_final(unsupported, model=f.profile.model)
                    f.sdk = FakeSDK([plan], model=f.profile.model)
                    response = f.client.post('/api/ai/messages' + ('/stream' if streaming else ''),
                        headers=f.headers, json={**f.envelope(streaming), 'question':
                            f'{prefix}，日本鳗鲡在溶解氧 2.11 mg/L 时的实验摄食率是多少？'})
                    if streaming:
                        self.assertEqual(response.status_code, 200)
                        stream = response.get_data(as_text=True)
                        events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith('data: ')]
                        self.assertNotIn('preview', [event['kind'] for event in events])
                        self.assertNotIn(unsupported, stream)
                        result = events[-1]['result']
                    else:
                        self.assertEqual(response.status_code, 502, response.get_json(silent=True))
                        result = response.get_json()['result']
                    response.close()
                    self.assertFalse(result['successful_turn'], result)
                    self.assertEqual(result['error_code'], 'ASSISTANT_SOURCE_REQUIREMENT_UNMET')
                    self.assertEqual(result['final_text'], '')

    def test_mixed_project_and_monitoring_lookups_keep_both_results(self):
        self.use_curated_content()
        f = self.fixture
        cases = (
            (WATER, {}, '日本鳗鲡在溶解氧 2.11 mg/L 时的实验摄食率是多少？另外查当前水质。',
             '已分别查询实验资料和当前水质。'),
            (HISTORY, {'lookback_minutes': 30, 'metrics': ['dissolved_oxygen_mg_l']},
             '日本鳗鲡在溶解氧 2.11 mg/L 时的实验摄食率是多少？另外列出过去半小时的溶氧历史。',
             '已分别查询实验资料和过去半小时的溶解氧监测数据。'),
        )
        for monitoring_tool, arguments, question, reply in cases:
            with self.subTest(monitoring_tool=monitoring_tool):
                f.sdk = FakeSDK([
                    sdk_tool(KNOWLEDGE, 'literature', json.dumps({'query': '日本鳗鲡溶解氧 2.11 mg/L 摄食'}),
                             f.profile.model),
                    sdk_tool(monitoring_tool, 'monitoring', json.dumps(arguments), f.profile.model),
                    sdk_final(reply, model=f.profile.model),
                ], model=f.profile.model)
                response = f.client.post('/api/ai/messages', headers=f.headers,
                    json={**f.envelope(), 'question': f'请查项目资料，{question}'})
                self.assertEqual(response.status_code, 200, response.get_json(silent=True))
                result = response.get_json()['result']
                response.close()
                self.assertTrue(result['successful_turn'], result)
                self.assertEqual(result['final_text'], reply)
                self.assertEqual([message['tool_call_id'] for message in f.sdk.bodies[-1]['messages']
                                  if message['role'] == 'tool'], ['literature', 'monitoring'])

    def test_exact_oxygen_comparison_only_publishes_matching_results_in_normal_and_streaming(self):
        self.use_curated_content()
        f = self.fixture
        question = ('请查项目资料，给出日本鳗鲡在溶解氧 2.11 mg/L 时的实验摄食率，'
                    '并与过去30分钟的溶解氧监测数据对比。')
        unsupported = '实验摄食率为95%。当前现场溶氧充足，摄食不受低氧抑制。'
        knowledge_args = json.dumps({'query': '日本鳗鲡 溶解氧 2.11 mg/L 摄食'})
        cases = (
            (30, 'dissolved_oxygen_mg_l', True),
            (10, 'dissolved_oxygen_mg_l', False),
            (30, 'temperature_c', False),
        )
        for streaming in (False, True):
            for lookback, metric, matching in cases:
                with self.subTest(streaming=streaming, lookback=lookback, metric=metric):
                    history_args = json.dumps({'lookback_minutes': lookback, 'metrics': [metric]})
                    calls = [(KNOWLEDGE, 'literature', knowledge_args), (HISTORY, 'history', history_args)]
                    if streaming:
                        plans = [tool_chunks(*call) for call in calls] + [final_chunks(unsupported)]
                    else:
                        plans = [sdk_tool(*call, f.profile.model) for call in calls]
                        plans.append(sdk_final(unsupported, model=f.profile.model))
                    f.sdk = FakeSDK(plans, model=f.profile.model)
                    response = f.client.post('/api/ai/messages' + ('/stream' if streaming else ''),
                        headers=f.headers, json={**f.envelope(streaming), 'question': question})
                    self.assertEqual(response.status_code, 200, response.get_json(silent=True))
                    if streaming:
                        stream = response.get_data(as_text=True)
                        events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith('data: ')]
                        self.assertNotIn('preview', [event['kind'] for event in events])
                        self.assertNotIn('95%', stream)
                        self.assertEqual(events[-1]['kind'], 'final', events[-1])
                        result = events[-1]['result']
                    else:
                        result = response.get_json()['result']
                    response.close()
                    self.assertTrue(result['successful_turn'], result)
                    self.assertEqual(len(f.sdk.bodies), 3)
                    payloads = {message['tool_call_id']: json.loads(message['content'])
                                for message in f.sdk.bodies[-1]['messages'] if message['role'] == 'tool'}
                    self.assertEqual(payloads['literature']['status'], 'OK')
                    self.assertEqual(payloads['history']['status'], 'PARTIAL')
                    self.assertEqual(set(payloads['history']['metrics']), {metric})
                    reply = result['final_text']
                    for evidence in ('2.11 mg/L', '8.9%', '10.2331/suisan.49.1335'):
                        self.assertIn(evidence, reply)
                    for fabricated in ('95%', '现场溶氧充足', '摄食不受低氧抑制'):
                        self.assertNotIn(fabricated, reply)
                    if matching:
                        for expected in ('模拟', '北京时间', '07:30', '08:00', '均值', '6.4', '部分覆盖', '高于'):
                            self.assertIn(expected, reply)
                    else:
                        self.assertIn('无法比较', reply)
                        self.assertNotIn('6.4 mg/L', reply)
                        self.assertNotIn('高于', reply)

    def test_curated_card_edit_and_status_do_not_keep_old_structured_evidence(self):
        from apps.knowledge.initial import initialize_curated_knowledge

        path = self.fixture.root / 'curated-edits.sqlite3'
        initialize_curated_knowledge(path)
        self.install_content(KnowledgeContentService(KnowledgeRepository(path, require_existing=True)))
        query = '日本鳗鲡溶解氧 2.11 mg/L 摄食'
        original, = self.content.search(query)
        card = self.content.get(original.evidence_id)
        disabled = self.content.set_status(card['id'], {'version': card['version'], 'status': 'DISABLED'})
        self.assertEqual(self.content.search(query), ())
        restored = self.content.set_status(card['id'], {'version': disabled['version'], 'status': 'ACTIVE'})
        self.assertEqual(self.content.search(query)[0].source_id, original.source_id)
        edited = self.content.edit(card['id'], {**VALUE, 'version': restored['version']})
        self.assertEqual(self.content.search(query), ())
        self.assertEqual(self.content.search(VALUE['title'])[0].source_id, edited['source_id'])
        self.assertEqual(edited['original_source_id'], original.source_id)

    def test_current_history_paths_still_use_monitoring_and_do_not_search_knowledge(self):
        f=self.fixture
        for streaming in (False,True):
            with patch.object(self.content,'search',side_effect=AssertionError('no implicit knowledge retrieval')):
                result=f.send((WATER,HISTORY),streaming)
            self.assertTrue(result['successful_turn'],result)
            f.assert_delivery_and_sources((WATER,HISTORY))
            self.assertEqual(len(f.sdk.bodies),3)

    def test_imported_builtin_edit_status_restore_and_safe_export_downloads(self):
        item=self.client.get('/api/knowledge').get_json()['items'][0]
        path='/api/knowledge/'+item['id']
        edited=self.client.patch(path,json={**VALUE,'version':item['version']},headers=self.headers).get_json()
        self.assertEqual(edited['origin'],'builtin');self.assertEqual(edited['original_source_id'],item['source_id'])
        self.assertNotEqual(edited['source_id'],item['source_id'])
        for status in ('DISABLED','DELETED','ACTIVE'):
            edited=self.client.post(path+'/status',json={'version':edited['version'],'status':status},headers=self.headers).get_json()
            hits=self.client.post('/api/knowledge/search',json={'query':'蓝莓浮岛'},headers=self.headers).get_json()['evidence']
            self.assertEqual(any(h['source']==edited['source_id'] for h in hits),status=='ACTIVE')
        before=self.content.repository.path.read_bytes()
        for selection in ('active','all'):
            exported=self.client.get('/api/knowledge/export?format=json&status='+selection)
            self.assertEqual(exported.status_code,200)
            self.assertEqual(exported.headers['Content-Type'],'application/json; charset=utf-8')
            self.assertIn('attachment; filename="fishery-knowledge-',exported.headers['Content-Disposition'])
            value=exported.get_json();self.assertEqual(value['count'],31)
            self.assertIn(edited,value['items'])
            markdown=self.client.get('/api/knowledge/export?format=markdown&status='+selection)
            self.assertEqual(markdown.status_code,200);self.assertIn(VALUE['body'],markdown.get_data(as_text=True))
        for query in ('format=../../private','format=sqlite','status=DELETED','path=C:/private','format=json&format=markdown'):
            self.assertEqual(self.client.get('/api/knowledge/export?'+query).status_code,400)
        for options in ({'base_url':'http://evil.invalid'}, {'environ_overrides':{'REMOTE_ADDR':'10.1.1.1'}},
                        {'headers':{'Origin':'http://evil.invalid'}}):
            self.assertEqual(self.client.get('/api/knowledge/export',**options).status_code,403)
        self.assertFalse(self.fixture.sdk.bodies)
        self.assertEqual(before,self.content.repository.path.read_bytes())
