"""Research entry tests: real SDK classes, memory HTTP, NEW data, no QQ I/O."""
import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI

from apps.ai_backend.credentials import CredentialStore
from apps.qq_bot.management_config import ROOT
from scripts.dev import check_qq_agent as driver
from scripts.dev.qq_agent_cases import CASES, CURRENT, HISTORY, KNOWLEDGE, SCORE


class AgentResearchRunnerTests(unittest.TestCase):
    def setUp(self):
        parent=ROOT/'outputs/test-tmp'
        parent.mkdir(parents=True,exist_ok=True)
        temporary=TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.http=[]
        self.mode='normal'
        self.before_response=None
        self.factory_plans={
            'C01':((CURRENT,{}),),
            'C05':((CURRENT,{}),),
            'C06':((CURRENT,{}),),
            'H01':((HISTORY,{'lookback_minutes':30}),),
            'K01':((KNOWLEDGE,{'query':'溶解氧 增氧'}),),
            'S01':((SCORE,{}),),
            'X01':((CURRENT,{}),(HISTORY,{'lookback_minutes':30})),
        }
        # Permit asyncio's private wakeup socket, never an actual HTTP socket.
        from apps.ai_backend.tests.test_execution import ExecutionTests
        ExecutionTests.setUp(self)
        original=CredentialStore.resolve
        def memory_only(store,*args,**kwargs):
            if store.private_location is not None or store.project_env_path is not None or type(store._process_env) is not dict:
                raise AssertionError('real credentials forbidden')
            return original(store,*args,**kwargs)
        guard=patch.object(CredentialStore,'resolve',memory_only)
        guard.start();self.addCleanup(guard.stop)

    def factory(self,runtime,remaining):
        async def respond(request):
            body=json.loads(request.content)
            self.http.append(body)
            question=next(m['content'] for m in reversed(body['messages']) if m['role']=='user')
            case=next(c for c in CASES if c.question==question or c.question in question)
            if self.mode=='timeout' and case.id=='C01':
                raise httpx.ReadTimeout('synthetic timeout',request=request)
            requested=self.factory_plans.get(case.id,())
            observed=[m for m in body['messages'] if m['role']=='tool']
            if len(observed)<len(requested):
                name,arguments=requested[len(observed)]
                if self.mode=='invalid_arguments' and case.id=='C01':arguments={'device_id':'not-authorized'}
                message=dict(role='assistant',content=None,tool_calls=[dict(id='synthetic-'+str(len(observed)),
                    type='function',function=dict(name=name,arguments=json.dumps(arguments)))])
                finish='tool_calls'
            else:
                answer='溶解氧是水中溶解的氧气。本地实验答复，不代表已执行现场操作。'
                if requested:answer='已整理本轮查询资料；过期或缺失的数据不能证明当前正常。'
                if self.mode=='false_claim' and case.id=='G01':answer='我已查询现场水质，一切正常。'
                message=dict(role='assistant',content=answer)
                finish='stop'
            if self.before_response is not None:self.before_response(case,body)
            return httpx.Response(200,json=dict(id='synthetic',object='chat.completion',created=0,
                model=runtime.model,choices=[dict(index=0,message=message,finish_reason=finish)],
                usage=dict(prompt_tokens=40,completion_tokens=20,total_tokens=60)))
        return AsyncOpenAI(api_key='fictional-only',base_url=runtime.base_url,max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond),trust_env=False,follow_redirects=False))

    def execute(self,ids,repeats=1):
        plan=driver.build_plan(ids,repeats=repeats)
        self.directory=self.root/('experiment-'+str(len(list(self.root.iterdir()))))
        with contextlib.redirect_stdout(io.StringIO()), \
                patch('apps.qq_bot.live_transport.LiveQQAPI',side_effect=AssertionError('QQ forbidden')), \
                patch('apps.qq_bot.ai_coordinator.QQAICoordinator.accept_delivery',side_effect=AssertionError('fake QQ acceptance forbidden')):
            report=driver.execute_experiment(plan,self.directory,factory=self.factory,approval_source='offline_test')
        return report

    def test_default_check_is_offline_no_credential_database_or_network(self):
        with patch('sqlite3.connect',side_effect=AssertionError('DB forbidden')), \
                patch.object(CredentialStore,'status',side_effect=AssertionError('key forbidden')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(driver.main(['--check','--suite','smoke']),0)
        status=json.loads(output.getvalue())
        self.assertEqual(status['code'],'AGENT_RESEARCH_CHECKED')
        self.assertFalse(status['credential_checked'])
        self.assertFalse(status['database_opened'])
        plan=status['plan']
        self.assertEqual(plan['max_model_requests'],plan['case_count']*3)
        self.assertEqual(plan['qq_network_requests'],0)
        self.assertEqual(plan['parallelism'],1)
        self.assertEqual(plan['retries'],0)
        self.assertEqual(plan['output_tokens_per_request'],2048)

    def test_declined_or_incomplete_delegated_approval_never_reads_credentials(self):
        for args,code in ((['--run','--suite','smoke'],'RESEARCH_APPROVAL_DECLINED'),
                          (['--run','--operator-authorized'],'RESEARCH_DELEGATED_AUTHORIZATION_NOTE_REQUIRED')):
            with self.subTest(args=args),patch('builtins.input',return_value=''), \
                    patch.object(CredentialStore,'status',side_effect=AssertionError('key forbidden')), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(SystemExit,code):driver.main(args)
        self.assertEqual(self.http,[])

    def test_tampered_plan_invalid_budget_or_repetition_reject_before_fixture(self):
        plan=driver.build_plan(['G01'])
        plan['max_model_requests']+=1
        with patch('sqlite3.connect',side_effect=AssertionError('DB forbidden')):
            with self.assertRaisesRegex(ValueError,'RESEARCH_PLAN_CHANGED'):
                driver.execute_experiment(plan,self.root/'tampered',factory=self.factory,approval_source='offline_test')
        for repeats in (0,-1,1.2,True):
            with self.subTest(repeats=repeats),self.assertRaises(ValueError):driver.build_plan(['G01'],repeats=repeats)
        for tokens in (0,4097):
            with self.subTest(tokens=tokens),self.assertRaises(Exception):driver.build_plan(['G01'],output_tokens=tokens)
        self.assertEqual(self.http,[])
        self.assertFalse((self.root/'tampered').exists())

    def test_four_tools_and_comparison_have_real_handler_receipts_without_qq_claims(self):
        report=self.execute(['G01','C01','H01','K01','S01','X01'])
        self.assertTrue(report['completed'],(report['code'],[(r['case_id'],r['code']) for r in report['cases']]))
        self.assertTrue(report['report_saved'])
        self.assertTrue(report['ram_cleared'])
        self.assertEqual(len(self.http),12)
        self.assertEqual(report['summary']['actual_model_http_requests'],12)
        self.assertEqual(report['summary']['actual_tool_executions'],6)
        self.assertEqual(report['summary']['expected_tool_match'],6)
        self.assertEqual(report['summary']['publication_allowed'],6)
        self.assertEqual(report['summary']['qq_submissions'],0)
        self.assertEqual(report['summary']['qq_history_commits'],0)
        rows=report['cases']
        self.assertEqual([r['model_requests'] for r in rows],[1,2,2,2,2,3])
        self.assertEqual([r['tool_names'] for r in rows],[[],[CURRENT],[HISTORY],[KNOWLEDGE],[SCORE],[CURRENT,HISTORY]])
        for row in rows:
            self.assertTrue(row['local_history_committed'])
            self.assertFalse(row['api_accepted'])
            self.assertFalse(row['qq_history_committed'])
            self.assertEqual(row['sdk_resources']['state'],'CLOSED')
            self.assertTrue(row['sdk_resources']['thread_exited'])
            self.assertFalse(row['automatic_retry'])
        self.assertTrue(all(body['max_tokens']==2048 for body in self.http))
        self.assertTrue((self.directory/'result.json').is_file())
        approval=json.loads((self.directory/'approval.json').read_text(encoding='utf8'))
        self.assertEqual(approval['source'],'offline_test')
        self.assertFalse(approval['real_provider'])
        self.assertFalse(approval['qq_authorized'])

    def test_local_multi_turn_context_is_labelled_and_not_reported_as_qq_delivery(self):
        report=self.execute(['M01','M02'])
        self.assertTrue(report['completed'],report['code'])
        self.assertEqual(len(self.http),2)
        self.assertEqual([r['history_turns_before'] for r in report['cases']],[0,1])
        transcript=str(self.http[1]['messages'])
        self.assertIn('LOCAL_REVIEW',transcript)
        self.assertIn('未发送QQ',transcript)
        self.assertEqual(report['summary']['local_history_commits'],2)
        self.assertEqual(report['summary']['qq_history_commits'],0)

    def test_invalid_arguments_are_recorded_once_and_next_independent_case_runs(self):
        self.mode='invalid_arguments'
        report=self.execute(['C01','G01'])
        self.assertTrue(report['completed'],report['code'])
        self.assertEqual(len(self.http),2)
        first,second=report['cases']
        self.assertEqual(first['code'],'INVALID_TOOL_ARGUMENTS')
        self.assertFalse(first['backend_completed'])
        self.assertFalse(first['local_history_committed'])
        self.assertEqual(first['tool_executions'],0)
        self.assertTrue(second['backend_completed'])
        self.assertTrue(second['local_history_committed'])
        self.assertEqual(first['sdk_resources']['state'],'CLOSED')

    def test_rejected_false_site_claim_is_retained_for_review_without_history(self):
        self.mode='false_claim'
        report=self.execute(['G01','G02'])
        self.assertTrue(report['completed'],report['code'])
        self.assertEqual(len(self.http),2)
        row=report['cases'][0]
        self.assertTrue(row['backend_completed'])
        self.assertFalse(row['publication_allowed'])
        self.assertFalse(row['local_history_committed'])
        self.assertEqual(row['publication_code'],'AGENT_CURRENT_SOURCE_MISSING')
        local=json.loads((self.directory/'case-1-G01.json').read_text(encoding='utf8'))
        self.assertIn('我已查询现场',local['model_text'])
        self.assertNotIn('我已查询现场',local['safe_reply'])
        self.assertEqual(report['summary']['publication_allowed'],1)

    def test_scope_revocation_stops_remaining_cases_without_more_model_io(self):
        def change_scope(case,body):
            if len(self.http)==1:
                path=next(self.directory.rglob('config/scope.json'))
                value=json.loads(path.read_text(encoding='utf8'))
                value['scope_sha256']='0'*64
                path.write_text(json.dumps(value),encoding='utf8')
        self.before_response=change_scope
        report=self.execute(['G01','G02'])
        self.assertFalse(report['completed'])
        self.assertEqual(len(self.http),1)
        self.assertEqual(len(report['cases']),1)
        self.assertEqual(report['cases'][0]['sdk_resources']['state'],'CLOSED')
        self.assertFalse(report['cases'][0]['local_history_committed'])
        self.assertTrue(report['report_saved'])

    def test_existing_report_directory_is_never_overwritten_or_replayed(self):
        directory=self.root/'old-report'
        directory.mkdir();old=directory/'result.json';old.write_text('preserved',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'RESEARCH_OUTPUT_NOT_EMPTY'):
            driver.execute_experiment(driver.build_plan(['G01']),directory,factory=self.factory,approval_source='offline_test')
        self.assertEqual(old.read_text(encoding='utf8'),'preserved')
        self.assertEqual(self.http,[])

    def test_http_timeout_is_not_retried_and_closed_failure_allows_next_case(self):
        self.mode='timeout'
        report=self.execute(['C01','G01'])
        self.assertTrue(report['completed'],report['code'])
        self.assertEqual(len(self.http),2)
        first,second=report['cases']
        self.assertFalse(first['publication_allowed'])
        self.assertFalse(first['local_history_committed'])
        self.assertEqual(first['model_http_requests'],1)
        self.assertEqual(first['sdk_resources']['state'],'CLOSED')
        self.assertTrue(first['sdk_resources']['thread_exited'])
        self.assertTrue(second['publication_allowed'])
        self.assertEqual(report['summary']['actual_model_http_requests'],2)
        self.assertFalse(report['automatic_retry'])

    def test_required_case_checkpoint_failure_stops_without_losing_usage_or_repeating(self):
        original=driver._private
        def fail_case(path,value):
            if path.name.startswith('case-'):raise OSError('synthetic checkpoint failure')
            return original(path,value)
        with patch.object(driver,'_private',fail_case):
            report=self.execute(['C01','G01'])
        self.assertFalse(report['completed'])
        self.assertTrue(report['report_saved'])
        self.assertEqual(len(self.http),2)  # Exactly the first Turn's Tool Calling.
        self.assertEqual(report['summary']['actual_model_http_requests'],2)
        self.assertEqual(report['summary']['executed'],1)
        self.assertGreater(report['summary']['input_tokens'],0)
        self.assertEqual(report['cases'][0]['sdk_resources']['state'],'CLOSED')
        self.assertFalse((self.directory/'case-1-G01.json').exists())

    def test_final_report_failure_never_repeats_provider_and_keeps_case_evidence(self):
        original=driver._private
        def fail_report(path,value):
            if path.name=='result.json':raise OSError('synthetic final report failure')
            return original(path,value)
        with patch.object(driver,'_private',fail_report):
            with self.assertRaises(OSError):self.execute(['G01'])
        self.assertEqual(len(self.http),1)
        self.assertTrue((self.directory/'case-1-G01.json').is_file())
        self.assertFalse((self.directory/'result.json').exists())
        self.assertTrue((self.directory/'cases.csv').is_file())

    def test_cleanup_failure_does_not_claim_confirmed_ram_clear(self):
        from apps.qq_bot.management_run import ManagementRun
        original=ManagementRun.close
        def close(host):
            original(host)
            raise OSError('synthetic close unconfirmed')
        with patch.object(ManagementRun,'close',close):report=self.execute(['G01'])
        self.assertFalse(report['completed'])
        self.assertEqual(report['code'],'RESEARCH_CLEANUP_FAILED')
        self.assertFalse(report['ram_cleared'])
        self.assertEqual(len(self.http),1)

    def test_real_credential_preflight_failure_saves_zero_request_blocked_report(self):
        from apps.ai_backend.credentials import CredentialFileError
        directory=self.root/'blocked-before-provider'
        with patch.object(driver,'_credential_status',side_effect=CredentialFileError()) as status, \
                patch('sqlite3.connect',side_effect=AssertionError('no business database')), \
                patch.object(httpx.AsyncClient,'send',side_effect=AssertionError('no provider I/O')), \
                contextlib.redirect_stdout(io.StringIO()):
            report=driver.execute_experiment(driver.build_plan(['G01']),directory,
                approval_source='delegated_user_task',authorization_note='SYNTHETIC_AUTHORIZATION_TEST')
        status.assert_called_once_with()
        self.assertEqual(report['code'],'CREDENTIAL_FILE_ERROR')
        self.assertEqual(report['stop_phase'],'CREDENTIAL_PREFLIGHT')
        self.assertFalse(report['completed'])
        self.assertTrue(report['real_provider'])  # Requested mode, not evidence of a request.
        self.assertFalse(report['provider_network_attempted'])
        self.assertEqual(report['provider_http_observations'],0)
        self.assertEqual(report['summary']['executed'],0)
        self.assertEqual(report['summary']['actual_model_requests'],0)
        self.assertEqual(report['summary']['actual_model_http_requests'],0)
        self.assertEqual(report['cases'],[])
        self.assertTrue(report['report_saved'])
        for filename in ('plan.json','approval.json','result.json','cases.csv'):
            self.assertTrue((directory/filename).is_file(),filename)
        self.assertEqual(self.http,[])


class ResearchAdmissionPacerTests(unittest.TestCase):
    class Clock:
        def __init__(self):self.value=0.;self.sleeps=[]
        def __call__(self):return self.value
        def sleep(self,seconds):
            self.sleeps.append(seconds);self.value+=seconds

    def test_six_admissions_are_immediate_and_seventh_waits_without_retrying_request(self):
        clock=self.Clock()
        pacer=driver.AdmissionPacer(clock=clock,sleep=clock.sleep)
        for _ in range(6):
            self.assertEqual(pacer.wait('host-a',member_limit=6,group_limit=20,deadline=100),0)
            pacer.record('host-a')
        waited=pacer.wait('host-a',member_limit=6,group_limit=20,deadline=100)
        self.assertAlmostEqual(waited,60.05,places=5)
        self.assertAlmostEqual(clock.value,60.05,places=5)
        self.assertTrue(clock.sleeps)
        self.assertLessEqual(max(clock.sleeps),.25)
        # wait did not consume a new admission or perform a Provider request.
        self.assertEqual(pacer.wait('host-a',member_limit=6,group_limit=20,deadline=100),0)

    def test_hosts_are_isolated_and_insufficient_deadline_rejects_before_wait(self):
        clock=self.Clock()
        pacer=driver.AdmissionPacer(clock=clock,sleep=clock.sleep)
        for _ in range(6):pacer.record(('host-a','member'))
        self.assertEqual(pacer.wait(('host-b','member'),member_limit=6,group_limit=20,deadline=100),0)
        with self.assertRaisesRegex(ValueError,'^RESEARCH_DURATION_REACHED$'):
            pacer.wait(('host-a','member'),member_limit=6,group_limit=20,deadline=60)
        self.assertEqual(clock.value,0)
        self.assertEqual(clock.sleeps,[])

    def test_operator_interrupt_while_waiting_propagates_without_consuming_new_admission(self):
        clock=self.Clock()
        def interrupt(_seconds):raise KeyboardInterrupt()
        pacer=driver.AdmissionPacer(clock=clock,sleep=interrupt)
        for _ in range(6):pacer.record('host-a')
        with self.assertRaises(KeyboardInterrupt):
            pacer.wait('host-a',member_limit=6,group_limit=20,deadline=100)
        self.assertEqual(clock.value,0)

    def test_model_statistics_exclude_zero_http_admission_failures(self):
        rows=[dict(case_id='G01',category='general',code='OK',seconds_total=10.,model_requests=1,
                   model_http_requests=1,tool_executions=0,branch='general',backend_completed=True,
                   publication_allowed=True,expected_tool_match=True),
              dict(case_id='A01',category='ambiguous',code='OK',seconds_total=20.,model_requests=2,
                   model_http_requests=2,tool_executions=1,branch='tools',backend_completed=True,
                   publication_allowed=True,expected_tool_match=None),
              dict(case_id='E01',category='adversarial',code='RATE_LIMITED',seconds_total=0.,model_requests=0,
                   model_http_requests=0,tool_executions=0,backend_completed=False,
                   publication_allowed=False,expected_tool_match=None)]
        summary=driver._summary(rows)
        self.assertEqual(summary['executed'],3)
        self.assertEqual(summary['model_executed'],2)
        self.assertEqual(summary['admission_not_model_evaluated'],1)
        self.assertEqual(summary['model_expected_tool_observational'],1)
        self.assertEqual(summary['actual_model_http_requests'],3)
        self.assertEqual(summary['seconds_median'],10.)
        self.assertEqual(summary['model_seconds_median'],15.)
        self.assertIsNone(summary['model_seconds_p95'])


if __name__=='__main__':unittest.main()
