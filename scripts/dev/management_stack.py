"""Thin orchestration of the existing Web/Simulator launcher plus an independent Bot."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

def request_stop(directory,role):
    from apps.qq_bot.trial_configuration import local_path,read_json,write_new
    directory=local_path(directory)
    if not directory.resolve().is_relative_to(ROOT/'outputs/management-stack'):
        raise RuntimeError('STACK_STOP_DIRECTORY_REJECTED')
    manifest=read_json(directory/'stack.json')
    if manifest.get('contract')!='management-stack@1':raise RuntimeError('STACK_STOP_DIRECTORY_REJECTED')
    path=directory/('stop-'+role+'.json')
    value={'nonce':manifest['nonce'],'role':role}
    if path.exists():
        if read_json(path)!=value:raise RuntimeError('STACK_STOP_RECORD_INVALID')
    else:write_new(path,value)
    return {'code':'STACK_STOP_REQUESTED','role':role,'run_directory':str(directory)}

def preflight(*,request=None,data_root=None,port=8766,with_bot=False,offline=False,bot_only=False):
    from scripts.dev.local_session import require_free_port
    if os.name!='nt':raise RuntimeError('STACK_WINDOWS_REQUIRED')
    if not bot_only:require_free_port(port)
    if with_bot:
        from apps.qq_bot.management_config import check_request
        selected,summary=check_request(request,offline=offline)
        if not selected.enabled:raise RuntimeError('AI_DISABLED')
        root=Path(summary['data_root'])
        if data_root is not None and data_root.resolve()!=root.resolve():raise RuntimeError('STACK_INSTANCE_MISMATCH')
    else:
        summary=None
        if data_root is None and request:
            from apps.qq_bot.management_config import load_request
            from apps.qq_bot.trial_configuration import read_json
            selected=load_request(request);data_root=Path(read_json(selected.inputs.monitoring_config)['data_root'])
        if data_root is None:raise RuntimeError('EXPLICIT_DATA_ROOT_REQUIRED')
        from apps.management_web.instance import validate_instance
        from apps.management_paths import ManagementPaths
        root=Path(data_root).resolve()
        from apps.management_process import probe_writer
        probe_writer(root)  # Reject unapproved old/formal instances before opening SQLite.
        validate_instance(ManagementPaths.resolve(ROOT,data_root=root))
    if with_bot:
        from apps.management_process import probe_writer
        probe_writer(root)
    return root,summary

def launch_stack(*,request=None,data_root=None,port=8766,scenario='normal',with_bot=False,
                 offline=False,bot_only=False,seconds=None,no_assistant=False,
                 interactive_scenario=False,open_browser=False,emit=print):
    from scripts.dev import local_session
    from scripts.dev.windows_job import own_process_tree
    from scripts.dev.console_job import ConsoleJob
    from scripts.dev.stack_console import stopped
    from apps.qq_bot.management_config import ensure_private_directory,process_lock
    from apps.ai_service.runtime.release_contracts import _hash
    from apps.qq_bot.trial_configuration import write_new
    root,summary=preflight(request=request,data_root=data_root,port=port,with_bot=with_bot,offline=offline,bot_only=bot_only)
    own_process_tree()
    parent=ROOT/'outputs/management-stack';parent.mkdir(parents=True,exist_ok=True)
    directory=parent/('stack-'+uuid.uuid4().hex);directory.mkdir()
    write_new(directory/'stack.json',dict(contract='management-stack@1',nonce=uuid.uuid4().hex,
        controller_pid=os.getpid(),with_bot=with_bot,bot_only=bot_only,offline=offline,port=port,
        data_root=str(root),request=str(request) if request else None))
    emit(json.dumps({'code':'STACK_STARTING','run_directory':str(directory),'controller_pid':os.getpid()},ensure_ascii=False),flush=True)
    children={};jobs={};seen={};stopping_at={};reaped=set();stop=threading.Event();monitor=None
    status_log=(directory/'controller.log').open('a',encoding='utf8',buffering=1)
    def report(value):
        line=json.dumps(value,ensure_ascii=False);status_log.write(line+'\n');emit(line,flush=True)
    def spawn(role,command=None,options=None):
        job=ConsoleJob();jobs[role]=job
        vector=[sys.executable,'-X','utf8','-I','-B','-u',str(ROOT/'scripts/dev/stack_console.py'),
            '--role',role,'--run-directory',str(directory),'--job',job.name]
        if role=='bot':
            vector+=['--request',str(Path(request).absolute())]
            if offline:vector+=['--offline-demo']
            if seconds:vector+=['--seconds',str(seconds)]
        else:vector+=['--',*command]
        kwargs=dict(options or {});kwargs.update(cwd=ROOT,creationflags=subprocess.CREATE_NEW_CONSOLE)
        child=subprocess.Popen(vector,**kwargs);children[role]=child
        report(dict(code='STACK_CHILD_CREATED',role=role,bootstrap_pid=child.pid,log=str(directory/(role+'.log'))))
        return child
    def monitor_loop():
        all_ready=False
        while not stop.wait(.1):
            states={}
            for role,child in tuple(children.items()):
                path=directory/(role+'.status.json')
                try:value=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
                except (OSError,ValueError):value={}
                if child.poll() is not None:
                    value={**value,'state':'EXITED','exit_code':child.returncode,
                           'code':value.get('code') if value.get('state')=='EXITED' else 'SERVICE_PROCESS_EXITED_WITHOUT_FINAL_STATUS'}
                    if role=='bot' and role not in reaped:
                        jobs[role].terminate();reaped.add(role)
                key=(value.get('state'),value.get('code'),value.get('exit_code'))
                if seen.get(role)!=key:
                    seen[role]=key
                    report(dict(code='STACK_SERVICE_STATE',role=role,pid=value.get('pid'),state=key[0] or 'STARTING',
                        service_code=key[1],exit_code=key[2],log=str(directory/(role+'.log'))))
                states[role]=value.get('state')
                bot_stop=False
                if role=='bot':
                    try:bot_stop=stopped(directory,'bot')
                    except Exception:bot_stop=True  # Only this owned Bot is stopped on corrupt control state.
                if role=='bot' and child.poll() is None and (value.get('state')=='EXITED' or bot_stop):
                    since=stopping_at.setdefault(role,time.monotonic())
                    if time.monotonic()-since>12:
                        jobs[role].terminate()
                        report(dict(code='STACK_OWNED_JOB_TERMINATED',role=role,report_complete=False))
            expected={'bot'} if bot_only else {'web','simulator'}|({'bot'} if with_bot else set())
            ready=expected==set(states) and all(states[k] in ('READY','RUNNING') for k in expected)
            if ready and not all_ready:
                report(dict(code='STACK_SERVICES_READY',roles=sorted(expected)));all_ready=True
    locks=ROOT/'outputs/management-stack/locks';ensure_private_directory(locks)
    result=0
    try:
        with ExitStack() as guards:
            # Same instance at a different port must not start a second writer pair.
            if not bot_only:guards.enter_context(process_lock(locks/('instance-'+_hash(str(root))[:24]+'.lock')))
            if with_bot:
                from apps.qq_bot.management_config import load_request
                from apps.qq_bot.trial_configuration import inputs_snapshot
                selected=load_request(request);app=inputs_snapshot(selected.inputs)[0].app_id
                # Prelaunch ownership: prevents a duplicate approval terminal before Bot takes its run lock.
                guards.enter_context(process_lock(locks/('bot-'+_hash([app,selected.inputs.group_id])[:24]+'.lock')))
            monitor=threading.Thread(target=monitor_loop,name='stack-status',daemon=False);monitor.start()
            if bot_only:
                child=spawn('bot')
                while child.poll() is None:
                    if stopped(directory,'all') or stopped(directory,'bot'):break
                    status=directory/'bot.status.json'
                    if status.exists() and json.loads(status.read_text(encoding='utf8')).get('state')=='EXITED':break
                    time.sleep(.1)
                result=child.returncode or 0
            else:
                def launch(command,**options):
                    role=command[command.index('--console-role')+1]
                    child=spawn(role,command,options)
                    if role=='simulator' and with_bot:spawn('bot')
                    return child
                def sleep(seconds_to_sleep):
                    if stopped(directory,'all'):raise KeyboardInterrupt()
                    # Bot control is handled independently by its controller/monitor.
                    time.sleep(seconds_to_sleep)
                result=local_session.run_local(scenario,port,assistant=not no_assistant,
                    data_root=root,show_terminals=True,interactive_scenario=interactive_scenario,
                    open_browser=open_browser,launch=launch,sleep=sleep,emit=lambda text:report(dict(code='STACK_WEB_SIMULATOR',message=text)))
    except KeyboardInterrupt:result=0
    except Exception as error:
        code=getattr(error,'code',str(error) if isinstance(error,RuntimeError) else 'STACK_START_FAILED')
        import re
        if not re.fullmatch('[A-Z][A-Z0-9_]{0,80}',str(code)):code='STACK_START_FAILED'
        report(dict(code=code));result=1
    finally:
        try:request_stop(directory,'all')
        except Exception:pass
        for role,child in tuple(children.items()):
            try:child.wait(timeout=12 if role=='bot' else 2)
            except subprocess.TimeoutExpired:
                jobs[role].terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
                report(dict(code='STACK_OWNED_JOB_TERMINATED',role=role,report_complete=False))
            finally:jobs[role].close()
        stop.set()
        if monitor:monitor.join(3)
        if 'bot' in children and children['bot'].poll() not in (0,None):result=1
        records={}
        for role,child in children.items():
            try:record=json.loads((directory/(role+'.status.json')).read_text(encoding='utf8'))
            except Exception:record={}
            if record.get('state')!='EXITED':record={**record,'code':'SERVICE_PROCESS_EXITED_WITHOUT_FINAL_STATUS'}
            records[role]=dict(bootstrap_pid=child.pid,pid=record.get('pid'),code=record.get('code'),
                exit_code=child.poll(),log=str(directory/(role+'.log')))
        try:write_new(directory/'result.json',dict(code='STACK_STOPPED',exit_code=result,
            children=records,all_services_succeeded=result==0,automatic_restart=False))
        except Exception:report(dict(code='STACK_REPORT_FAILED'));result=1
        report(dict(code='STACK_STOPPED',exit_code=result,run_directory=str(directory)));status_log.close()
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description='Management 三终端；默认仅 Web+Simulator')
    p.add_argument('--request',type=Path);p.add_argument('--data-root',type=Path);p.add_argument('--port',type=int,default=8766)
    p.add_argument('--scenario',default='normal',choices=tuple(k for k,_ in __import__('scripts.dev.local_session',fromlist=['DEMO_SCENARIOS']).DEMO_SCENARIOS))
    p.add_argument('--with-bot',action='store_true');p.add_argument('--bot-only',action='store_true')
    p.add_argument('--offline-demo',action='store_true');p.add_argument('--check',action='store_true')
    p.add_argument('--seconds',type=int);p.add_argument('--no-assistant',action='store_true')
    p.add_argument('--interactive-scenario',action='store_true')
    p.add_argument('--open-browser',action='store_true')
    p.add_argument('--stop-directory',type=Path);p.add_argument('--stop-role',choices=('bot','all'),default='all')
    args=p.parse_args(argv)
    try:
        if args.stop_directory:print(json.dumps(request_stop(args.stop_directory,args.stop_role),ensure_ascii=False));return 0
        if not 1<=args.port<=65535:raise RuntimeError('INVALID_LOCAL_PORT')
        if args.seconds is not None and not 1<=args.seconds<=1800:raise RuntimeError('INVALID_RUN_DURATION')
        if args.bot_only:args.with_bot=True
        if args.check:
            root,summary=preflight(request=args.request,data_root=args.data_root,port=args.port,with_bot=args.with_bot,offline=args.offline_demo,bot_only=args.bot_only)
            print(json.dumps(dict(code='STACK_PREFLIGHT_OK',data_root=str(root),bot=args.with_bot,summary=summary),ensure_ascii=False));return 0
        return launch_stack(request=args.request,data_root=args.data_root,port=args.port,scenario=args.scenario,
            with_bot=args.with_bot,offline=args.offline_demo,bot_only=args.bot_only,seconds=args.seconds,no_assistant=args.no_assistant,
            interactive_scenario=args.interactive_scenario,open_browser=args.open_browser)
    except Exception as error:
        from apps.qq_bot.management_cli import emit
        emit(getattr(error,'code',str(error) if isinstance(error,RuntimeError) else 'STACK_PREFLIGHT_FAILED'));return 1

if __name__=='__main__':raise SystemExit(main())
