"""Real Qwen research over the current QQ Web-Agent, with no QQ transport.

Check is offline. Run requires a local human approval or an explicitly delegated
operator task. Only newly generated synthetic instances are used. Local review
history is labelled as such; it is never a QQ delivery receipt or qualification.
"""
import argparse
from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import statistics
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from apps.ai_service.runtime.release_contracts import _hash
from apps.qq_bot.conversations import ConversationOptions
from scripts.dev.qq_agent_cases import CASES, create_fixture, refresh_fixture

CONTRACT='management-qq-agent-provider-research@1'
HISTORY_CONTRACT='local-research-context-not-qq-delivery@1'
AUTHORIZATION_SOURCES=('local_operator','delegated_user_task','offline_test')


class AdmissionPacer:
    """Research scheduling only; leave the real Adapter's rolling limits intact.

    Record after prepare returns, conservatively later than its rate claim.
    No locks, model retries, or production admission bypasses are involved.
    """
    def __init__(self, *, clock=None, sleep=None):
        self.clock=clock or time.monotonic
        self.sleep=sleep or time.sleep
        self.admissions={}

    def wait(self,key,*,member_limit,group_limit,deadline):
        limit=min(member_limit,group_limit)  # The research Host has one member/group.
        if type(limit) is not int or limit<1:
            raise ValueError('RESEARCH_ADMISSION_LIMIT_INVALID')
        started=self.clock()
        queue=self.admissions.setdefault(key,deque())
        announced=False
        while True:
            now=self.clock()
            if now>=deadline:raise ValueError('RESEARCH_DURATION_REACHED')
            while queue and queue[0]+60.05<=now:queue.popleft()
            if len(queue)<limit:return max(0.0,now-started)
            remaining=queue[0]+60.05-now
            if now+remaining>=deadline:raise ValueError('RESEARCH_DURATION_REACHED')
            if not announced:
                emit('RESEARCH_ADMISSION_WAIT',seconds=round(remaining,3))
                announced=True
            self.sleep(min(.25,remaining,deadline-now))

    def record(self,key):
        self.admissions.setdefault(key,deque()).append(self.clock())


def safe_code(error,default='RESEARCH_EXECUTION_FAILED'):
    value=getattr(error,'code',None)
    if value is None and isinstance(error,ValueError):value=str(error)
    return value if isinstance(value,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,80}',value) else default


def emit(code,**fields):
    print(json.dumps(dict(code=code,**fields),ensure_ascii=False),flush=True)


def _case_id(case):return case.id


def _selected(ids):
    names=tuple(ids)
    lookup={_case_id(c):c for c in CASES}
    if not names or len(set(names))!=len(names) or any(n not in lookup for n in names):
        raise ValueError('RESEARCH_CASES_INVALID')
    return tuple(lookup[n] for n in names)


def build_plan(cases=None, repeats=1, output_tokens=2048):
    from apps.ai_service.channel_management_agent import prepared_scope, PROMPT_ID
    from apps.ai_service.channel_trial import PRESET, PRICE_INPUT, PRICE_OUTPUT, CONTEXT_RESERVATION
    from apps.ai_service.runtime.assistant import assistant_profile
    if type(repeats) is not int or not 1<=repeats<=100:
        raise ValueError('RESEARCH_REPEATS_INVALID')
    selected=tuple(CASES if cases is None else cases)
    selected=_selected(tuple(c.id if hasattr(c,'id') else c for c in selected))
    profile=assistant_profile(PRESET)
    scope=prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True),output_tokens)
    paths=('scripts/dev/check_qq_agent.py','scripts/dev/qq_agent_cases.py')
    count=len(selected)*repeats
    reserve=((CONTEXT_RESERVATION*PRICE_INPUT+Decimal(output_tokens)*PRICE_OUTPUT)*3/Decimal(1000000))
    return dict(contract=CONTRACT,purpose='LOCAL_PROVIDER_RESEARCH_NOT_QQ_ACCEPTANCE',
        provider=profile.service_id,model=profile.model,preset=PRESET,prompt_id=PROMPT_ID,
        runtime_scope_sha256=_hash(scope),case_ids=[c.id for c in selected],
        case_bank_sha256=_hash([asdict(c) for c in selected]),repeats=repeats,
        case_count=count,max_model_requests=count*3,max_model_requests_per_turn=3,
        max_tool_calls_per_turn=2,output_tokens_per_request=output_tokens,seconds_per_turn=90,
        batch_seconds=count*90+300,parallelism=1,retries=0,
        admission_schedule='RESPECT_HOST_QQ_ROLLING_WINDOW@1',
        source='NEW_SYNTHETIC_SIMULATOR_AND_BUNDLED_KNOWLEDGE_ONLY',
        qq_network_requests=0,qq_submissions=0,qq_history_committed=False,
        local_history_contract=HISTORY_CONTRACT,history_scope='PER_REPEAT_SCENARIO_CONVERSATION',
        input_price_cny_per_million=str(PRICE_INPUT),output_price_cny_per_million=str(PRICE_OUTPUT),
        conservative_reservation_cny=str(reserve*count),price_status='PROJECT_STATIC_ESTIMATE_NOT_CLOUD_BILL',
        content_storage='PRIVATE_SYNTHETIC_QUESTION_SAFE_REPLY_AND_MODEL_TEXT_FOR_LOCAL_REVIEW',
        implementation={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths})


def _check_plan(plan):
    if type(plan) is not dict or plan!=build_plan(plan.get('case_ids',()),
            repeats=plan.get('repeats'),output_tokens=plan.get('output_tokens_per_request')):
        raise ValueError('RESEARCH_PLAN_CHANGED')


def _private(path,value):
    from apps.ai_backend.secure_files import write_private
    _publish_private(path,(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n').encode())


def _publish_private(path,body):
    """Publish once only after the private write/fsync succeeded; retain failures as pending evidence."""
    from apps.ai_backend.secure_files import write_private
    temporary=path.with_name(path.name+'.pending-'+uuid.uuid4().hex)
    write_private(temporary,body)
    if os.name=='nt':os.rename(temporary,path)  # Windows rename refuses an existing destination.
    else:
        os.link(temporary,path)  # Exclusive destination creation, no overwrite on POSIX either.
        temporary.unlink()


def _new_directory(path):
    from apps.ai_backend.secure_files import guard_path
    from apps.qq_bot.management_config import ensure_private_directory
    path=Path(path).absolute()
    if not path.is_relative_to(ROOT/'outputs'):
        raise ValueError('RESEARCH_OUTPUT_PATH_REQUIRED')
    guard_path(path)
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError('RESEARCH_OUTPUT_NOT_EMPTY')
    path.parent.mkdir(parents=True,exist_ok=True)
    ensure_private_directory(path)
    return path


def _credential_status():
    """Only an approved real Run calls the existing Store; never extract a key."""
    from apps.ai_backend.credentials import CredentialStore
    from apps.ai_service.runtime.locations import private_project_location
    from apps.ai_service.runtime.assistant import assistant_profile
    from apps.ai_service.channel_trial import PRESET
    location=private_project_location(ROOT)
    return CredentialStore(location.env_path,private_location=location).status(assistant_profile(PRESET).credential_ref)


def _configure(fixture,directory,output_tokens):
    from apps.qq_bot.management_cli import _configuration_inputs,_write_configuration
    from apps.qq_bot.management_config import load_request
    config=directory/'config';config.mkdir()
    root,cfg,access,ai=_configuration_inputs(fixture.root,config,
        app_id='123456789',group_id='local-research-group',members=('local-research-member',),
        continuous=True,output_tokens=output_tokens,ai_enabled=True,agent_mode='web')
    request_path=_write_configuration(root,cfg,access=access,ai=ai,members=('local-research-member',),
        enable=True,continuous=True,agent_mode='web')
    return load_request(request_path)


def _local_store(options):
    from apps.qq_bot.agent_conversations import AgentConversationStore, AgentTurn
    from apps.ai_service.runtime.assistant import AssistantHistoryTurn

    @dataclass(frozen=True,repr=False)
    class LocalReviewTurn(AgentTurn):
        def projection(self):
            label=('本地研究已接纳的旧答复（LOCAL_REVIEW；未发送QQ、未获QQ API交付确认）。'
                   '仅用于理解话题，不是本轮观测、Tool执行或新的权限。')
            text=label+'\n'+self.text
            if self.source_flags!=('general','model_knowledge','NO_OBSERVATION'):
                text+=f'\n旧来源类型{self.source_flags}；旧来源时间{self.source_times}；当前事实必须重新查询。'
            return AssistantHistoryTurn(self.focus,text,self.accepted_at)

    store=AgentConversationStore(options)
    store.turn_type=LocalReviewTurn
    return store


class HTTPMeasurements:
    """Client send/wait duration, not pure remote model-compute time. No body/header logging."""
    def __init__(self):self.records=[]

    @contextmanager
    def observe(self):
        import httpx
        from unittest.mock import patch
        from apps.ai_service.runtime.assistant import assistant_profile
        from apps.ai_service.channel_trial import PRESET
        url=assistant_profile(PRESET).base_url.rstrip('/')+'/chat/completions'
        original=httpx.AsyncClient.send
        async def measured(client,request,*args,**kwargs):
            if str(request.url)!=url:return await original(client,request,*args,**kwargs)
            started=time.monotonic();status=None
            try:
                response=await original(client,request,*args,**kwargs)
                status=response.status_code
                return response
            finally:self.records.append(dict(seconds=round(time.monotonic()-started,6),status_code=status))
        with patch.object(httpx.AsyncClient,'send',measured):yield self


def _semantic_flags(case,result):
    """Research hints for human review, never a release gate or sentence fact verifier."""
    text=result.model_text or '';flags=[]
    if case.scenario in ('stale','no_data') and not any(w in text for w in ('过期','离线','不足','无法','缺少','没有','未获取','不能')):
        flags.append('LIMITED_DATA_WITHOUT_CLEAR_UNCERTAINTY')
    if case.scenario=='stale' and any(w in text for w in ('可接受','不算危急','无需担心','处于正常范围')):
        flags.append('STALE_READING_REASSURANCE_REVIEW')
    if re.search(r'前\s*1/9',text):flags.append('HISTORY_COVERAGE_POSITION_REVIEW')
    if re.search(r'(?:相同|相等|一致).{0,25}(?:说明|证明).{0,25}(?:没有|无|未).{0,10}上报',text):
        flags.append('EQUAL_VALUE_CAUSAL_CLAIM_REVIEW')
    if len(result.publication.text if result.publication else '')>900:flags.append('LONG_CHAT_REPLY_REVIEW')
    return flags


def _tool_match(case,tools):
    return case.tool_choice_matches(tools)


def _trace_facts(task):
    """Read only this synthetic run's allowlisted Trace, including failed Tool steps."""
    path=task.service.traces.path
    if not path.is_file():return dict(trace_available=False)
    records=[json.loads(line) for line in path.read_text(encoding='utf8').splitlines() if line]
    execution=next((r for r in reversed(records) if r.get('kind')=='read_only_tool_conversation'),None)
    assistant=next((r for r in reversed(records) if r.get('kind')=='assistant_turn'),{})
    if execution is None:return dict(trace_available=False)
    steps=[s for s in execution['steps'] if s['kind']=='tool']
    started=[s for s in steps if s.get('handler_started')]
    return dict(trace_available=True,tool_steps=steps,
        tool_names=[s['tool_name'] for s in started],tool_executions=len(started),
        history_turns_sent=assistant.get('history_turns_sent'),
        history_bytes_sent=assistant.get('history_bytes_sent'),
        agent_trace_seconds=execution.get('timing',{}).get('total_ms',0)/1000)


def _commit_local(coordinator,plan,result):
    """A separate local review operation; deliberately no DeliveryReceipt or accept_delivery."""
    coordinator.validate_delivery_candidate(plan,result)
    plan.handle.check();plan.handle.assert_resources_closed()
    publication=result.publication
    if publication is None or not publication.allowed or not publication.history_allowed:
        return 'LOCAL_REVIEW_NOT_COMMITTED'
    snapshot=plan.prepared.channel_history
    if snapshot is None:return 'LOCAL_REVIEW_NO_SNAPSHOT'
    snapshot.authority.validate(snapshot,snapshot.scope_sha256)
    times,flags=result.history_metadata()
    code=coordinator.conversations.commit(snapshot,turn_id='local-review-'+plan.id,
        text=publication.text,text_sha256=hashlib.sha256(publication.text.encode()).hexdigest(),
        accepted_at=datetime.now(timezone.utc).isoformat(),source_times=times,source_flags=flags)
    return 'LOCAL_REVIEW_COMMITTED' if code=='HISTORY_COMMITTED' else 'LOCAL_REVIEW_DISABLED'


def _summary(rows):
    successful=[r for r in rows if r.get('backend_completed')]
    elapsed=sorted(r['seconds_total'] for r in rows)
    evaluated=[r for r in rows if r.get('model_http_requests',0)>0]
    model_elapsed=sorted(r['seconds_total'] for r in evaluated)
    def percentile(values,q):
        import math
        return values[max(0,math.ceil(len(values)*q)-1)] if len(values)>=30 else None
    counts=Counter(r.get('code','UNKNOWN') for r in rows)
    return dict(executed=len(rows),backend_completed=len(successful),
        model_executed=len(evaluated),admission_not_model_evaluated=len(rows)-len(evaluated),
        model_expected_tool_match=sum(r.get('expected_tool_match') is True for r in evaluated),
        model_expected_tool_mismatch=sum(r.get('expected_tool_match') is False for r in evaluated),
        model_expected_tool_observational=sum(r.get('expected_tool_match') is None for r in evaluated),
        publication_allowed=sum(bool(r.get('publication_allowed')) for r in rows),
        expected_tool_match=sum(r.get('expected_tool_match') is True for r in rows),
        expected_tool_mismatch=sum(r.get('expected_tool_match') is False for r in rows),
        expected_tool_observational=sum(r.get('expected_tool_match') is None for r in rows),
        semantic_review_cases=sum(bool(r.get('semantic_flags')) for r in rows),
        actual_model_requests=sum(r.get('model_requests',0) for r in rows),
        actual_model_http_requests=sum(r.get('model_http_requests',0) for r in rows),
        actual_tool_executions=sum(r.get('tool_executions',0) for r in rows),
        local_history_commits=sum(bool(r.get('local_history_committed')) for r in rows),
        qq_submissions=0,qq_history_commits=0,
        input_tokens=sum(r.get('usage',{}).get('input_tokens',0) for r in rows),
        output_tokens=sum(r.get('usage',{}).get('output_tokens',0) for r in rows),
        usage_complete_cases=sum(r.get('usage_complete') is True for r in rows if r.get('model_requests',0)),
        usage_incomplete_cases=sum(r.get('usage_complete') is not True for r in rows if r.get('model_requests',0)),
        estimated_usage_cost_cny=str(sum((Decimal(r.get('observed_usage_cost_cny','0')) for r in rows),Decimal(0))),
        billing_confirmed=False,codes=dict(counts),
        seconds_median=statistics.median(elapsed) if elapsed else None,
        seconds_p95=percentile(elapsed,.95),seconds_min=min(elapsed) if elapsed else None,
        seconds_max=max(elapsed) if elapsed else None,
        model_seconds_median=statistics.median(model_elapsed) if model_elapsed else None,
        model_seconds_p95=percentile(model_elapsed,.95),
        model_seconds_min=min(model_elapsed) if model_elapsed else None,
        model_seconds_max=max(model_elapsed) if model_elapsed else None,
        research_admission_wait_seconds=sum(r.get('research_admission_wait_seconds',0) for r in rows),
        human_answer_quality='NOT_AUTOMATICALLY_VERIFIED')


def execute_experiment(plan,directory,*,factory=None,approval_source=None,authorization_note=None):
    from apps.qq_bot.management_run import ManagementRun
    from apps.qq_bot.ai_coordinator import QQAICoordinator
    from apps.qq_bot.intent import GatewayMention
    _check_plan(plan)
    if approval_source not in AUTHORIZATION_SOURCES or (factory is None and approval_source=='offline_test'):
        raise ValueError('RESEARCH_APPROVAL_REQUIRED')
    directory=_new_directory(directory)
    _private(directory/'plan.json',plan)
    _private(directory/'approval.json',dict(contract=CONTRACT,plan_sha256=_hash(plan),
        source=approval_source,approved_at=datetime.now(timezone.utc).isoformat(),
        authorization_reference=authorization_note,
        real_provider=factory is None,qq_authorized=False,resume=False,old_approval_imported=False))
    rows=[];hosts={};contexts={};stop='RESEARCH_COMPLETED';phase='CREDENTIAL_PREFLIGHT'
    deadline=time.monotonic()+plan['batch_seconds'];http=HTTPMeasurements();selected=_selected(plan['case_ids'])
    pacer=AdmissionPacer()
    try:
        if factory is None and _credential_status().availability!='PRESENT':
            raise ValueError('PROVIDER_CREDENTIAL_UNAVAILABLE_NO_REQUESTS')
        phase='CASE_EXECUTION'
        with http.observe():
            for repeat in range(1,plan['repeats']+1):
                for case in selected:
                    _check_plan(plan)
                    if time.monotonic()>=deadline:stop='RESEARCH_DURATION_REACHED';break
                    key=(repeat,case.scenario)
                    if key not in hosts:
                        group=directory/f'repeat-{repeat}-{case.scenario}';group.mkdir()
                        fixture=create_fixture(group/'instance',case.scenario,lambda:datetime.now(timezone.utc))
                        request=_configure(fixture,group,plan['output_tokens_per_request'])
                        run=group/'run';run.mkdir()
                        host=ManagementRun(request,run,async_client_factory=factory)
                        host.store.close();host.store=_local_store(host.options)
                        host.approve(host.plan(),confirmed=True)
                        coordinator=QQAICoordinator(host.access,host.monitoring,host.base_service,
                            config=host.config,conversations=host.store,session_run=host)
                        owner=object();coordinator._mention_owner=owner
                        hosts[key]=(host,coordinator,owner,fixture)
                    host,coordinator,owner,fixture=hosts[key]
                    refresh_fixture(fixture,lambda:datetime.now(timezone.utc))
                    context=case.conversation_id or 'independent-'+case.id
                    if contexts.get(key)!=context:host.store.invalidate()
                    contexts[key]=context
                    row=dict(case_id=case.id,category=case.category,scenario=case.scenario,repeat=repeat,
                        expectation=case.expectation,question_sha256=_hash(case.question),
                        conversation_id=case.conversation_id,history_turns_before=host.store.counts()['turns'],
                        backend_completed=False,publication_allowed=False,local_history_committed=False,
                        qq_submissions=0,qq_history_committed=False,api_accepted=False,
                        client_display_confirmed=False,automatic_retry=False,semantic_flags=[],
                        tool_names=[],model_requests=0,model_http_requests=0,tool_executions=0,
                        research_admission_wait_seconds=0)
                    row['fixture_oracle']=fixture.current_oracle()
                    task=None;result=None;started=time.monotonic();http_start=len(http.records)
                    try:
                        host.check()
                        intent=coordinator.classify(case.question,command_priority=False)
                        if not coordinator.is_agent_intent(intent):
                            if intent.kind=='clear':host.store.invalidate()
                            row.update(code='FIXED_PROGRAM_RESPONSE',fixed_branch=True,
                                publication_allowed=True,expected_tool_match=_tool_match(case,()),safe_reply=intent.text)
                        else:
                            waited=pacer.wait(key,member_limit=host.access.member_per_minute,
                                group_limit=host.access.group_per_minute,deadline=deadline)
                            row['research_admission_wait_seconds']=round(waited,6)
                            started+=waited  # Report research pacing separately from request execution.
                            if waited:host.check()  # Revoke/config/resource checks still run after waiting.
                            message_id=f'research-{repeat}-{case.id}'
                            raw=json.dumps(dict(op=0,t='GROUP_AT_MESSAGE_CREATE',d=dict(id=message_id,
                                group_openid=request.inputs.group_id,author=dict(member_openid=request.members[0],bot=False),
                                timestamp=datetime.now(timezone.utc).isoformat(),content='/问AI '+case.question))).encode()
                            mention=GatewayMention(owner,host.access.app_id,message_id,hashlib.sha256(raw).hexdigest())
                            try:
                                task=coordinator.prepare(raw,transport_app_id=host.access.app_id,mention=mention,
                                    capacity_check=lambda _:None)
                            finally:
                                pacer.record(key)  # A failed prepare is never retried or made into new allowance.
                            task.handle.limit_turn(min(90,max(.001,deadline-time.monotonic())))
                            result=coordinator.execute(task)
                            task.handle.assert_resources_closed()
                            row.update(code=result.error_code or 'OK',backend_completed=result.completed,
                                branch=result.branch,model_requests=result.model_requests,
                                tool_executions=result.tool_executions,tool_names=list(result.source_kinds),
                                expected_tool_match=_tool_match(case,result.source_kinds),
                                receipts=[asdict(r) for r in result.receipts],source_notes=list(result.source_notes),
                                model_text=result.model_text)
                            if result.completed:
                                coordinator.validate_delivery_candidate(task,result)
                                row.update(publication_allowed=result.publication.allowed,
                                    publication_code=result.publication.code,safe_fallback=result.publication.facts_only,
                                    safe_reply=result.publication.text,semantic_flags=_semantic_flags(case,result))
                                row['local_history_committed']=_commit_local(coordinator,task,result)=='LOCAL_REVIEW_COMMITTED'
                    except KeyboardInterrupt:
                        stop='RESEARCH_INTERRUPTED';row['code']=stop
                        if task:task.handle.cancel();task.handle.abort_io()
                    except Exception as error:
                        row['code']=safe_code(error)
                    finally:
                        if task:
                            try:
                                session=task.service._channel_trial
                                turn=session.report()
                                row.update(model_http_requests=turn.get('model_http_requests',0),
                                    model_requests=turn.get('model_requests',row['model_requests']),
                                    usage=turn.get('usage',{}),observed_usage_cost_cny=turn.get('observed_usage_cost_cny','0'),
                                    sdk_resources=turn.get('sdk_resources'),usage_complete=turn.get('usage_complete',False),
                                    sdk_request_attempts=turn.get('sdk_request_attempts',0))
                                row.update(_trace_facts(task))
                                row['expected_tool_match']=_tool_match(case,row['tool_names'])
                            finally:
                                coordinator.discard(task,outcome=dict(state='LOCAL_REVIEWED',code=row['code'],
                                    api_accepted=False,history_code='NO_QQ_DELIVERY'))
                        row['seconds_total']=round(time.monotonic()-started,6)
                        row['http_client_timings']=http.records[http_start:]
                        row['local_review_passed']=bool(row['publication_allowed'] and row.get('expected_tool_match') is not False)
                        rows.append(row)
                        try:_private(directory/f'case-{repeat}-{case.id}.json',dict(row,question=case.question))
                        except Exception:
                            row['report_error']='RESEARCH_CASE_CHECKPOINT_FAILED'
                            raise ValueError('RESEARCH_CASE_CHECKPOINT_FAILED') from None
                        emit('RESEARCH_CASE_FINISHED',case_id=case.id,repeat=repeat,reason=row['code'],
                            backend_completed=row['backend_completed'],publication_allowed=row['publication_allowed'],
                            expected_tool_match=row.get('expected_tool_match'),model_http_requests=row['model_http_requests'],
                            tool_executions=row['tool_executions'],seconds=row['seconds_total'])
                    if stop!='RESEARCH_COMPLETED':break
                    # No retries. Ordinary closed failures become recorded samples;
                    # unsafe resources/ownership/scope/ledger failures stop all new I/O.
                    try:host.check()
                    except Exception as error:
                        stop=safe_code(error,'RESEARCH_SAFETY_STOP');break
                if stop!='RESEARCH_COMPLETED':break
                # A completed repeat has no resumable allowance. Close its RAM,
                # journal and owner handles rather than retaining all runs.
                for key in tuple(hosts):
                    if key[0]==repeat:
                        hosts[key][0].close();del hosts[key];contexts.pop(key,None)
    except KeyboardInterrupt:stop='RESEARCH_INTERRUPTED'
    except Exception as error:stop=safe_code(error,'RESEARCH_FAILED_STOP')
    finally:
        cleared=True
        for host,_,_,_ in hosts.values():
            try:host.close()
            except Exception:stop='RESEARCH_CLEANUP_FAILED';cleared=False
        report=dict(contract=CONTRACT,code=stop,plan_sha256=_hash(plan),
            completed=stop=='RESEARCH_COMPLETED' and len(rows)==plan['case_count'],
            real_provider=factory is None,qq_network_requests=0,automatic_retry=False,resume=False,
            stop_phase=phase,transport='REAL_PROVIDER_HTTPS' if factory is None else 'MEMORY_MOCK_HTTP',
            provider_network_attempted=factory is None and bool(http.records),
            provider_http_observations=len(http.records) if factory is None else 0,
            sdk_http_client_observations=len(http.records),
            runtime_scope_sha256=plan['runtime_scope_sha256'],summary=_summary(rows),
            cases=[{k:v for k,v in row.items() if k not in ('model_text','safe_reply','receipts','source_notes')} for row in rows],
            report_saved=True,ram_cleared=cleared)
        try:
            import csv,io
            buffer=io.StringIO(newline='')
            columns=('case_id','category','scenario','repeat','code','backend_completed','publication_allowed',
                'expected_tool_match','model_requests','model_http_requests','tool_executions',
                'local_history_committed','research_admission_wait_seconds','seconds_total','observed_usage_cost_cny')
            writer=csv.DictWriter(buffer,fieldnames=columns,extrasaction='ignore');writer.writeheader()
            writer.writerows(rows)
            _publish_private(directory/'cases.csv',buffer.getvalue().encode('utf-8-sig'))
            _private(directory/'result.json',report)
        except Exception:
            report['report_saved']=False;report['code']='RESEARCH_REPORT_FAILED'
            emit('RESEARCH_REPORT_FAILED');raise
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description='当前四工具QQ Agent本机Qwen研究；默认Check，不连接QQ')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--check',action='store_true');mode.add_argument('--run',action='store_true')
    parser.add_argument('--suite',choices=('smoke','full'),default='full')
    parser.add_argument('--cases',type=int);parser.add_argument('--repeats',type=int,default=1)
    parser.add_argument('--case-ids');parser.add_argument('--output-tokens',type=int,default=2048)
    parser.add_argument('--operator-authorized',action='store_true')
    parser.add_argument('--authorization-note',default='')
    args=parser.parse_args(argv)
    selected=list(CASES)
    if args.case_ids:selected=list(_selected(args.case_ids.split(',')))
    elif args.suite=='smoke':
        selected=[]
        for category in ('general','current','history','knowledge','score','comparison'):
            found=next((c for c in CASES if c.category==category),None)
            if found is not None:selected.append(found)
    if args.cases is not None:
        if not 1<=args.cases<=len(selected):raise SystemExit('RESEARCH_CASES_INVALID')
        selected=selected[:args.cases]
    plan=build_plan(selected,args.repeats,args.output_tokens)
    emit('AGENT_RESEARCH_CHECKED',plan=plan,plan_sha256=_hash(plan),credential_checked=False,database_opened=False)
    if not args.run:return 0
    if args.operator_authorized:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}',args.authorization_note):
            raise SystemExit('RESEARCH_DELEGATED_AUTHORIZATION_NOTE_REQUIRED')
        source='delegated_user_task'
    else:
        digest=_hash(plan)[:12]
        print('真实调用Qwen；仅新建合成数据，不连接QQ。模型正文仅保存到本机私有研究目录。',flush=True)
        if input('批准请输入 APPROVE AGENT '+digest+'：').strip()!='APPROVE AGENT '+digest:
            raise SystemExit('RESEARCH_APPROVAL_DECLINED')
        source='local_operator'
    for name in ('openai','httpx','httpcore','websockets'):logging.getLogger(name).disabled=True
    parent=ROOT/'outputs/agent-research';parent.mkdir(parents=True,exist_ok=True)
    directory=parent/('experiment-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12])
    report=execute_experiment(plan,directory,approval_source=source,authorization_note=args.authorization_note or None)
    emit(report['code'],summary=report['summary'],completed=report['completed'],result_file=str(directory/'result.json'))
    return 0 if report['completed'] else 1


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError) as error:
        code=str(error) if isinstance(error,ValueError) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,80}',str(error)) else 'RESEARCH_LOCAL_ERROR'
        emit(code);raise SystemExit(1) from None
