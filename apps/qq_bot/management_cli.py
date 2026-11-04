"""Explicit local commands. Default/Check are offline; Run asks the human in this terminal."""
import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import getpass
import json
from pathlib import Path
import threading
import time

from apps.ai_backend.credentials import CredentialStore, CredentialSnapshot, CredentialStatus
from apps.ai_backend.providers import AuthSpec
from apps.ai_backend.project_env import ProjectEnvWriter
from apps.ai_backend.secure_files import exclusive_lock, private_directory
from apps.ai_service.runtime.locations import private_project_location
from apps.ai_service.runtime.release_contracts import _hash
from .management_config import ROOT, MARKER, RISK, check_request, prepared_scope, ensure_private_directory, process_lock, inputs_snapshot
from apps.ai_service.management_channel_budget import CHANNEL_BUDGET, DEFAULT_RUN_BUDGET_CNY
from .management_run import ManagementRun
from .run_consent import RunLimits
from .trial_configuration import write_new, local_path
from .contracts import BotError

SECRET_REF = 'FISHERY_QQ_APP_SECRET'


def emit(code, **fields):
    # Callers supply only allowlisted scalar metadata, never exception/request bodies.
    import re
    code = str(code)
    if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,80}',code): code='MANAGEMENT_BOT_FAILED'
    print(json.dumps({'code':code,**fields},ensure_ascii=False,default=str),flush=True)


def initialize_demo(data_root, config_dir, *, app_id, group_id, members, enable=False):
    from apps.management_paths import ManagementPaths
    from apps.management_web.instance import initialize_instance
    from apps.monitoring.repository import MonitoringRepository
    from apps.monitoring.service import MonitoringService
    from apps.simulator.generator import Simulator
    from .ai_configuration import QQAIConfig, QQAIGrant
    from .contracts import BotConfig, GroupAccess
    from .configuration import app_identifier
    from .conversations import ConversationOptions
    app_identifier(app_id)
    if not 1<=len(members)<=4:raise BotError('RUN_MEMBERS_NOT_APPROVED')
    root, cfg = local_path(data_root), local_path(config_dir)
    if root==cfg or root.is_relative_to(cfg) or cfg.is_relative_to(root):raise BotError('INITIALIZATION_PATH_CONFLICT')
    if (not root.resolve().is_relative_to(ROOT/'outputs') or root == ROOT/'outputs/demo-instance'
            or not cfg.resolve().is_relative_to(ROOT/'outputs')):
        raise BotError('ISOLATED_OUTPUTS_DIRECTORY_REQUIRED')
    if root.exists() or cfg.exists(): raise BotError('INITIALIZATION_TARGET_EXISTS')
    if not root.parent.is_dir() or not cfg.parent.is_dir(): raise BotError('INITIALIZATION_PARENT_MISSING')
    access = BotConfig(app_id,(GroupAccess(group_id,'sim-pond-1',tuple(members),('current',)),))
    ai = QQAIConfig(True,budget=CHANNEL_BUDGET,grants=(QQAIGrant(group_id,tuple(members),'sim-pond-1'),))
    paths = ManagementPaths.resolve(ROOT,data_root=root)
    initialize_instance(paths); cfg.mkdir()
    now=datetime.now(timezone.utc)
    simulator=Simulator(start=now-timedelta(seconds=30),device_id='sim-pond-1',session_id='m3-initialization')
    service=MonitoringService(MonitoringRepository(paths.monitoring),clock=lambda:now)
    for _ in range(3): service.ingest(simulator.advance())
    write_new(root/'qq-isolated-instance.json',dict(contract=MARKER,root=str(root.resolve()),
        instance_id='management-isolated',device_id='sim-pond-1',source='SIMULATOR'))
    for name,value in (('access.json',dict(schema_version=1,app_id=app_id,groups=[asdict(g) for g in access.groups])),
                       ('ai.json',dict(schema_version=1,**asdict(ai))),
                       ('monitoring.json',dict(schema_version=1,instance_id='management-isolated',data_root=str(root.resolve()),devices=['sim-pond-1']))):
        write_new(cfg/name,value)
    (cfg/'policy').mkdir()
    from .trial_configuration import TrialInputs
    inputs=TrialInputs.parse(dict(access_file=str(cfg/'access.json'),ai_config=str(cfg/'ai.json'),
        monitoring_config=str(cfg/'monitoring.json'),policy_directory=str(cfg/'policy'),group_id=group_id,member_id=members[0]))
    inputs_snapshot(inputs)  # Initializes only this new, isolated Bot policy; no global policy writes.
    scope=prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True))
    write_new(cfg/'request.json',dict(schema_version=1,enabled=enable,inputs=inputs.dictionary(),
        limits=asdict(RunLimits(total_budget_cny=DEFAULT_RUN_BUDGET_CNY)),members=list(members),scope_sha256=_hash(scope)))
    return cfg/'request.json'


def save_qq_secret(*, replace=False):
    # Only explicit human command enters this path. Never used by Check/stack preflight.
    location=private_project_location(ROOT)
    store=CredentialStore(location.env_path,private_location=location)
    writer=ProjectEnvWriter(location.env_path.parent,store,require_git_ignored=False)
    status=writer.inspect(SECRET_REF,AuthSpec.REQUIRED_BEARER)
    secret=getpass.getpass('输入 Management QQ AppSecret（不回显）：')
    if not secret or len(secret)>4096 or not secret.isascii() or any(c.isspace() or not c.isprintable() for c in secret):
        raise BotError('INVALID_QQ_SECRET')
    writer.mutate(SECRET_REF,AuthSpec.REQUIRED_BEARER,action='replace' if replace else 'create',
                  expected_revision=status['revision'],secret=secret)
    emit('MANAGEMENT_QQ_SECRET_SAVED')


def run(request_path, directory, *, offline=False, seconds=None, stop_requested=lambda:False, read=input, emit_status=emit):
    request, summary=check_request(request_path,offline=offline)
    if not request.enabled: raise BotError('AI_DISABLED')
    from .gateway import validate_run_duration
    duration=request.limits.seconds if seconds is None else seconds
    # Fail before approval/credentials if an override exceeds this run's consent.
    validate_run_duration(duration,max_seconds=request.limits.seconds)
    import logging
    for name in ('openai','httpx','httpcore','websockets'):
        logging.getLogger(name).disabled=True  # Dedicated Bot process only; no wire/body logging.
    directory=local_path(directory)
    directory.mkdir(exist_ok=False)
    locks=ROOT/'outputs/qq-bot/locks'; locks.parent.mkdir(parents=True,exist_ok=True)
    ensure_private_directory(locks)
    key=_hash([inputs_snapshot(request.inputs)[0].app_id, request.inputs.group_id])[:24]
    host=scheduler=gateway=transport=api=notifier=None
    code='MANAGEMENT_BOT_STOPPED'; failures=[]
    with process_lock(locks/('bot-'+key+'.lock')):
        try:
            from .demo_runtime import provider_factory
            host=ManagementRun(request,directory,async_client_factory=provider_factory if offline else None)
            if summary.get('event_notifications'):
                host.enable_event_notifications(request.event_recipient_file)
            plan=host.plan(); digest=_hash(plan)[:12]
            emit_status('MANAGEMENT_BOT_APPROVAL_REQUIRED',summary=summary,plan_sha256=_hash(plan))
            if not offline:
                if plan.get('event_notifications'):
                    print('另行批准：向已验证好友（摘要 '+plan['event_notifications']['recipient_ref']+
                        '）主动发送本次指定设备的 SIMULATOR 事件、观测时间。新异常、升级、可靠消退各一次；'
                        '不调用模型，未知送达不重发，每10秒最多1次、每日最多100次。仅本进程有效。',flush=True)
                answer=read('如同意本进程模型、披露、General 风险及费用，请输入 APPROVE MANAGEMENT '+digest+'：')
                if answer.strip()!='APPROVE MANAGEMENT '+digest: raise BotError('MANAGEMENT_APPROVAL_DECLINED')
            host.approve(plan,confirmed=True)  # Offline consent cannot construct real I/O.
            write_new(directory/'approval.json',dict(contract=host.scope['contract'],plan_sha256=_hash(plan),
                offline=offline,source='local_operator' if not offline else 'synthetic_test',resume=False))
            from .live_transport import LiveQQAPI,LiveQQTransport,live_connector
            from .demo_runtime import qq_client,FakeSocket
            if offline:
                supplier=lambda:CredentialSnapshot('fictional-only',CredentialStatus('PRESENT','test',False))
            else:
                location=private_project_location(ROOT)
                store=CredentialStore(location.env_path,private_location=location)
                # Resolve only after explicit approval; no private values are logged.
                supplier=lambda:store.resolve(SECRET_REF)
            api=LiveQQAPI(host.access.app_id,supplier,permit=host.permit,client=qq_client() if offline else None)
            transport=LiveQQTransport(api,host)
            from .ai_coordinator import QQAICoordinator
            from .ai_scheduler import QQAIJobScheduler
            from .ai_routing import OfflineQQAIRouter
            from .adapter import QQAdapter
            from .service import ReadOnlyQueries
            from .gateway import QQGateway
            coordinator=QQAICoordinator(host.access,host.monitoring,host.base_service,config=host.config,
                conversations=host.store,session_run=host)
            scheduler=QQAIJobScheduler(coordinator,transport,failure_feedback=True)
            adapter=QQAdapter(host.access,ReadOnlyQueries(host.monitoring),mode='QQ_PASSIVE_READY')
            router=OfflineQQAIRouter(adapter,scheduler)
            connector=(lambda _:FakeSocket(host.access.app_id,request.inputs.group_id,request.members[0])) if offline else live_connector(host.permit)
            gateway=QQGateway(host.access.app_id,api,adapter,trial_router=router,connector=connector,
                emit=lambda c,**fields:emit_status(c,**fields))
            if summary.get('event_notifications'):
                from .event_notifications import NotificationPermit,NoticeJournal,EventNotifier
                permit=NotificationPermit(host)
                journal_dir=ROOT/'outputs/qq-bot/event-notices'
                journal_dir.parent.mkdir(parents=True,exist_ok=True);ensure_private_directory(journal_dir)
                journal=NoticeJournal(journal_dir,permit.audience,clock=host.clock)
                try:
                    notifier=EventNotifier(permit,api,journal,
                        connected=lambda:gateway.ready.is_set() and transport.connected,
                        clock=host.clock,emit=emit_status)
                except Exception:journal.close();raise
                notifier.start()
            def drive():
                try: gateway.run(duration,max_seconds=request.limits.seconds)
                except Exception as error: failures.append(getattr(error,'code','MANAGEMENT_GATEWAY_FAILED'))
            worker=threading.Thread(target=drive,name='management-qq-gateway',daemon=False)
            worker.start()
            try:
                while worker.is_alive():
                    if stop_requested(): code='MANAGEMENT_OPERATOR_STOP'; break
                    host.check(); worker.join(.1)
                    for status in scheduler.take_statuses():emit_status('AI_TASK_FINISHED',**status)
                if failures: code=failures[0]
            except KeyboardInterrupt: code='MANAGEMENT_OPERATOR_INTERRUPTED'
            except Exception as error: code=getattr(error,'code','MANAGEMENT_RUN_FAILED')
            finally:
                gateway.stop.set()
                guard=gateway._active_guard
                if guard and guard._socket:
                    try:guard._socket.shutdown(2);guard._socket.close()
                    except OSError:pass
                worker.join(12)
                if worker.is_alive():raise BotError('MANAGEMENT_GATEWAY_STOP_FAILED')
        except (KeyboardInterrupt,EOFError): code='MANAGEMENT_OPERATOR_INTERRUPTED'
        except Exception as error: code=getattr(error,'code','MANAGEMENT_BOT_FAILED')
        finally:
            if notifier:
                try:notifier.close()
                except Exception:code='EVENT_NOTIFICATION_STOP_FAILED'
                host._notice_report=notifier.report()
            if transport:transport.close()
            if api:api.close()
            if api and offline:api._client.close()  # Controller owns this injected memory client.
            if host:
                try:
                    if scheduler:
                        report=host.stop(scheduler,code=code)
                        for status in scheduler.take_statuses():emit_status('AI_TASK_FINISHED',**status)
                    else:
                        host.close();report=host.report(code);write_new(directory/'result.json',report)
                    emit_status('MANAGEMENT_BOT_REPORT_SAVED',stop_code=code,
                        consumed_turns=report['quota']['consumed_turns'],ram_cleared=report['ram_cleared'])
                except Exception:code='MANAGEMENT_REPORT_OR_CLEANUP_FAILED'
            else:
                try:write_new(directory/'result.json',dict(code=code,network_requests=0))
                except Exception:code='MANAGEMENT_REPORT_WRITE_FAILED'
    emit_status(code)
    return 0 if code in ('MANAGEMENT_BOT_STOPPED','MANAGEMENT_OPERATOR_STOP','MANAGEMENT_OPERATOR_INTERRUPTED','RUN_EXPIRED') else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description='Management 专属独立 Bot；默认无网络')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('check','run'):
        p=sub.add_parser(name);p.add_argument('--request',type=Path,required=True);p.add_argument('--offline-demo',action='store_true')
        if name=='run':p.add_argument('--run-directory',type=Path,required=True);p.add_argument('--seconds',type=int)
    p=sub.add_parser('prepare-demo');p.add_argument('--data-root',type=Path,required=True);p.add_argument('--config-directory',type=Path,required=True)
    p.add_argument('--app-id',default='123456789');p.add_argument('--group-id',default='fictional-group')
    p.add_argument('--member',action='append',default=None);p.add_argument('--enable-ai',action='store_true')
    p=sub.add_parser('save-secret');p.add_argument('--replace',action='store_true')
    args=parser.parse_args(argv)
    try:
        if args.command=='check':emit('MANAGEMENT_CHECK',summary=check_request(args.request,offline=args.offline_demo)[1]);return 0
        if args.command=='run':return run(args.request,args.run_directory,offline=args.offline_demo,seconds=args.seconds)
        if args.command=='save-secret':save_qq_secret(replace=args.replace);return 0
        path=initialize_demo(args.data_root,args.config_directory,app_id=args.app_id,group_id=args.group_id,
            members=tuple(args.member or ['fictional-member']),enable=args.enable_ai)
        emit('MANAGEMENT_ISOLATED_DEMO_CREATED',request=str(path));return 0
    except Exception as error:emit(getattr(error,'code','MANAGEMENT_CONFIGURATION_FAILED'));return 1

if __name__=='__main__':raise SystemExit(main())
