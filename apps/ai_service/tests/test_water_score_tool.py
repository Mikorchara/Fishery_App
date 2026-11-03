"""Synthetic SQLite + Fake SDK only; no user data, credentials or network."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.ai_backend.tests import test_execution as offline_guard
from apps.ai_backend.tests.support import FakeSDK,sdk_tool,sdk_final,tool_chunks,final_chunks
from apps.ai_backend.credentials import CredentialStore
from apps.ai_backend.observability import JsonlTraceSink
from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
from apps.ai_backend.tool_conversation import ToolModelTransport
from apps.ai_service.service import ManagementAssistantService
from apps.ai_service.score_execution import load_score_config,SCORE_TOOL_NAMES
from apps.ai_service.business_tools.water_quality_score import score_payload,WATER_QUALITY_SCORE as SCORE,valid_evaluation
from apps.ai_service.runtime import assistant,sources
from apps.knowledge.tests.support import reference_knowledge
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from apps.management_web.app import create_app
from apps.management_web.ai_adapter import ManagementAssistant


class WaterScoreTests(unittest.TestCase):
    def setUp(self):
        offline_guard.ExecutionTests.setUp(self)
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.now=datetime(2026,11,2,tzinfo=timezone.utc);self.sequence=0
        self.monitoring=MonitoringService(MonitoringRepository(self.root/'synthetic.sqlite3'),
            device_names={'pond-a':'合成测试池','pond-b':'另一个测试池'},clock=lambda:self.now)

    def observe(self,temperature=26,ph=7.5,oxygen=6.4,*,samples=10,device='pond-a'):
        self.now+=timedelta(seconds=10);self.sequence+=1
        sim=Simulator(start=self.now-timedelta(seconds=10),device_id=device,session_id='score-'+str(self.sequence),seed=42)
        batch=sim.advance(10);batch['visual']=None
        for field,value in [('temperature_c',temperature),('ph',ph),('dissolved_oxygen_mg_l',oxygen)]:
            count=samples if field=='ph' else 10
            item=batch['water']['metrics'][field]
            item.update(mean=value if count else None,min=value if count else None,max=value if count else None,
                latest=value if count else None,valid_samples=count)
        self.monitoring.ingest(batch)

    def test_rule_bands_weights_caps_and_all_clear_boundary(self):
        for values,expected,grade,cap in [((26,7.5,6.4),100,'GOOD',100),
                ((20,7,5),100,'GOOD',100),((30,8.5,5),100,'GOOD',100),
                ((19,7.5,6),79,'WARNING',79),((26,6.9,6),79,'WARNING',79),
                ((26,7.5,4),79,'WARNING',79),((14,7.5,6),39,'CRITICAL',39),
                ((26,9.1,6),39,'CRITICAL',39),((26,7.5,2.2),39,'CRITICAL',39),
                ((26,7.5,.5),19,'CRITICAL',19)]:
            with self.subTest(values=values):
                self.observe(*values);result=score_payload(self.monitoring,'pond-a')
                self.assertEqual(result['score'],expected);self.assertEqual(result['grade'],grade)
                self.assertEqual(result['score_cap'],cap);self.assertTrue(valid_evaluation(result))
                self.assertEqual(sum(c['weight_percent'] for c in result['components'].values()),100)
                self.assertEqual(result['source_kind'],'simulator');self.assertIn('NOT PROFESSIONAL',result['limitation'])
                self.assertEqual(result['query_evaluated_at'],self.now.isoformat())

    def test_unavailable_evidence_never_gets_partial_normalized_or_historical_score(self):
        self.assertEqual(score_payload(self.monitoring,'pond-a')['status'],'NO_DATA')
        for count in [0,5]:
            self.observe(samples=count);result=score_payload(self.monitoring,'pond-a')
            self.assertEqual(result['status'],'NOT_SCORABLE');self.assertIsNone(result['score'])
            self.assertEqual(result['components'],{});self.assertTrue(valid_evaluation(result))
        self.observe();self.now+=timedelta(seconds=31)
        result=score_payload(self.monitoring,'pond-a');self.assertIsNone(result['score']);self.assertIn('NOT_FRESH',result['unscorable_reasons'])
        self.now+=timedelta(seconds=100);result=score_payload(self.monitoring,'pond-a')
        self.assertIn('NOT_ONLINE',result['unscorable_reasons']);self.assertTrue(valid_evaluation(result))
        with self.assertRaisesRegex(ValueError,'UNKNOWN_MONITORING_DEVICE'):score_payload(self.monitoring,'unauthorized')

    def test_one_capture_read_only_and_tampered_score_rejected(self):
        self.observe(oxygen=2.2)
        before=self.monitoring.repository.path.read_bytes()
        with patch.object(self.monitoring,'capture_water',wraps=self.monitoring.capture_water) as read:
            result=score_payload(self.monitoring,'pond-a');self.assertEqual(read.call_count,1)
        self.assertEqual(before,self.monitoring.repository.path.read_bytes())
        for key,value in [('score',100),('grade','GOOD'),('scoring_version','unknown')]:
            changed={**result,key:value};self.assertFalse(valid_evaluation(changed))

    def configure(self,enabled=True):
        self.profile=assistant.assistant_profile('dashscope-qwen38-flash-r1')
        self.sdk=FakeSDK([],model=self.profile.model)
        self.backend=ManagementAssistantService(self.monitoring,knowledge=reference_knowledge(),
            credentials=CredentialStore(process_env={self.profile.credential_ref:'fictional-score-key'}),
            traces=JsonlTraceSink(self.root/'trace.jsonl',tool_names=SCORE_TOOL_NAMES),policy_directory=self.root/'policy',
            gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=self.sdk.factory),
            scoring_config=load_score_config(enable_trial=enabled))
        self.web=ManagementAssistant(self.backend);self.client=create_app(data_service=self.monitoring,ai=self.web).test_client()
        self.headers={'X-Management-AI':self.web.browser_token}
        cfg=self.client.get('/api/ai/tool-policy').get_json()
        response=self.client.post('/api/ai/tool-policy',json={'epoch':cfg['epoch'],'revision':cfg['revision'],
            'selected_tools':[SCORE]},headers=self.headers)
        self.assertEqual(response.status_code,200)

    def request(self,streaming=False,**overrides):
        device=overrides.get('device_id','pond-a')
        config=self.client.get('/api/ai/bootstrap?device='+device).get_json()
        execution=config['presets'][0]['streaming' if streaming else 'execution']
        control=self.client.post('/api/ai/requests',json={'epoch':config['epoch']},headers=self.headers).get_json()
        return {'preset_id':self.profile.preset_id,'device_id':'pond-a','question':'请给当前水质实验评分','history':[],
            'epoch':config['epoch'],'revision':execution['revision'],'confirm_network':True,**control,**overrides}

    def test_normal_streaming_score_commit_receipt_and_sdk_close(self):
        self.observe();self.configure()
        for streaming in [False,True]:
            for state in ['fresh','stale','no_data']:
                with self.subTest(streaming=streaming,state=state):
                    device='pond-b' if state=='no_data' else 'pond-a'
                    if state=='fresh':self.observe()
                    if state=='stale':self.now+=timedelta(seconds=31)
                    self.sdk=FakeSDK([tool_chunks(SCORE,'c1','{}'),final_chunks('实验结果，请按限制解读。')] if streaming else
                        [sdk_tool(SCORE,'c1','{}',self.profile.model),sdk_final('实验结果，请按限制解读。',model=self.profile.model)],model=self.profile.model)
                    captured=[];original=assistant.AssistantService.send
                    def collect(owner,*a,**kw):
                        result=original(owner,*a,**kw);captured.append(result);return result
                    with patch.object(assistant.AssistantService,'send',collect):
                        response=self.client.post('/api/ai/messages'+('/stream' if streaming else ''),
                            json=self.request(streaming,device_id=device),headers=self.headers)
                        text=response.get_data(as_text=True);self.assertEqual(response.status_code,200,text);response.close()
                    result=json.loads([line[6:] for line in text.splitlines() if line.startswith('data: ')][-1])['result'] if streaming else json.loads(text)['result']
                    self.assertTrue(result['successful_turn'],result)
                    receipt=captured[0].source_ledger.entries[0].receipt
                    self.assertTrue(receipt.score_evaluation_completed)
                    self.assertEqual(receipt.has_score,state=='fresh')
                    self.assertTrue(sources.requirement_satisfied_by_ledger(sources.SourceRequirement.CURRENT_SCORE_EVALUATION,captured[0].source_ledger))
                    self.assertEqual(len(self.sdk.bodies),2)
                    self.assertEqual([d['function']['name'] for d in self.sdk.bodies[0]['tools']],[SCORE])
                    self.assertTrue(all(c.closed and (not c.stream or c.stream.closed) for c in self.sdk.clients))

    def test_opt_in_policy_confirmation_scope_and_revision_guards(self):
        self.observe();self.configure(False)
        config=self.client.get('/api/ai/bootstrap?device=pond-a').get_json()
        self.assertNotIn(SCORE,config['tools']);self.assertFalse(self.backend.tool_authorization()['score_trial']['enabled'])
        self.configure(True)
        self.assertEqual(self.client.post('/api/ai/messages',json=self.request(confirm_network=False),headers=self.headers).status_code,409)
        body=self.request();current=self.backend.management_policy.snapshot()
        self.backend.management_policy.save([],expected_revision=current.revision)
        self.assertNotEqual(self.client.post('/api/ai/messages',json=body,headers=self.headers).status_code,200)
        self.assertEqual(self.sdk.bodies,[])
        current=self.backend.management_policy.snapshot();self.backend.management_policy.save([SCORE],expected_revision=current.revision)
        config=self.backend._scoring_config
        self.backend._scoring_config=replace(config,scopes_json=tuple(raw.replace('"calls":2','"calls":1') for raw in config.scopes_json))
        self.assertFalse(self.backend.bootstrap('pond-a')['presets'][0]['execution']['can_send'])
        self.assertEqual(self.sdk.bodies,[])

    def test_launcher_score_opt_in_is_explicit_and_web_only(self):
        from scripts.dev.local_session import commands
        self.assertNotIn('--assistant-score-trial',commands('python','normal',8766,42)[0])
        web,sim=commands('python','normal',8766,42,score_trial=True)
        self.assertIn('--assistant-score-trial',web);self.assertNotIn('--assistant-score-trial',sim)
        with self.assertRaisesRegex(RuntimeError,'SCORE_TRIAL_REQUIRES_ASSISTANT'):
            commands('python','normal',8766,42,assistant=False,score_trial=True)

    def test_score_parameters_cannot_override_frozen_device(self):
        self.observe();self.configure()
        self.sdk=FakeSDK([sdk_tool(SCORE,'c1','{"device_id":"pond-b"}',self.profile.model)],model=self.profile.model)
        with patch.object(self.monitoring,'capture_water',wraps=self.monitoring.capture_water) as read:
            response=self.client.post('/api/ai/messages',json=self.request(),headers=self.headers)
            result=response.get_json();response.close()
        self.assertIn('INVALID_TOOL_ARGUMENTS',json.dumps(result));self.assertEqual(len(self.sdk.bodies),1)
        self.assertEqual(read.call_count,0)

    def test_management_web_knowledge_requirement_and_qq_tool_boundary_preserved(self):
        kwargs=dict(credentials=CredentialStore(process_env={}),
                    traces=JsonlTraceSink(self.root/'boundary.trace.jsonl'),
                    policy_directory=self.root/'boundary-policy',scoring_config=load_score_config(enable_trial=True))
        with self.assertRaisesRegex(ValueError,'KNOWLEDGE_SERVICE_REQUIRED'):
            ManagementAssistantService(self.monitoring,**kwargs)
        backend=ManagementAssistantService.monitoring_only(self.monitoring,**kwargs)
        self.assertIsNone(backend.scoring_registry)
        self.assertEqual(backend.formal_registry.registered_names(),('get_current_water_quality',))
        self.assertNotIn(SCORE,backend.history_registry.registered_names())

    def test_management_content_knowledge_scopes_normal_and_streaming(self):
        from apps.knowledge.tests.support import seed
        from apps.knowledge.repository import KnowledgeRepository
        from apps.knowledge.service import KnowledgeContentService
        from apps.ai_service.score_execution import resolve_score_trial
        from apps.ai_backend.tools.policy import ToolPolicy
        from apps.ai_service.business_tools.registry import bind_tools
        self.observe();path=self.root/'knowledge.sqlite3';seed(path)
        knowledge=KnowledgeContentService(KnowledgeRepository(path))
        profile=assistant.assistant_profile('dashscope-qwen38-flash-r1')
        registry=bind_tools(self.monitoring,'pond-a',knowledge,include_history=True,include_score=True)
        policy=ToolPolicy('assistant',True,(SCORE,))
        for transport in (ToolModelTransport.NORMAL,ToolModelTransport.STREAMING):
            decision=resolve_score_trial(load_score_config(enable_trial=True),profile,policy,registry,knowledge,
                device_id='pond-a',epoch='synthetic',policy_revision='synthetic',transport=transport)
            self.assertTrue(decision.can_send)
