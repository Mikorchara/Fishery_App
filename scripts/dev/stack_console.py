"""One service per console; tee logs, report actual Python PID, no shell command strings."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

def write_status(directory,role,**fields):
    from apps.ai_backend.secure_files import guard_path
    guard_path(directory)
    target=directory/(role+'.status.json');guard_path(target,regular=True)
    manifest=json.loads((directory/'stack.json').read_text(encoding='utf8'))
    import ctypes
    ctypes.windll.kernel32.GetConsoleWindow.restype=ctypes.c_void_p
    value=dict(schema_version=1,nonce=manifest['nonce'],role=role,pid=os.getpid(),
               console_hwnd=ctypes.windll.kernel32.GetConsoleWindow(),log=str(directory/(role+'.log')),**fields)
    temp=directory/('.'+role+'-'+uuid.uuid4().hex+'.tmp')
    with temp.open('x',encoding='utf8') as stream:
        json.dump(value,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
    # Windows readers can briefly hold the old status file without delete
    # sharing. Retry only this atomic status replacement; never restart a
    # service or repeat file creation/fsync/business work on its behalf.
    deadline=time.monotonic()+.5
    while True:
        try:
            os.replace(temp,target)
            break
        except OSError as error:
            remaining=deadline-time.monotonic()
            if (os.name!='nt' or getattr(error,'winerror',None) not in (5,32,33)
                    or remaining<=0):
                raise
            time.sleep(min(.01,remaining))

def stopped(directory,role):
    manifest=json.loads((directory/'stack.json').read_text(encoding='utf8'))
    for name in ('all',role):
        path=directory/('stop-'+name+'.json')
        if path.exists():
            try:
                if json.loads(path.read_text())=={'nonce':manifest['nonce'],'role':name}:return True
            except Exception:raise RuntimeError('STACK_STOP_RECORD_INVALID') from None
    return False

class Tee:
    def __init__(self,console,log):self.console,self.log=console,log
    def write(self,text):self.log.write(text);self.log.flush();return self.console.write(text)
    def flush(self):self.log.flush();self.console.flush()
    def __getattr__(self,key):return getattr(self.console,key)

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--role',choices=('web','simulator','bot'),required=True)
    p.add_argument('--run-directory',type=Path,required=True);p.add_argument('--job',required=True)
    p.add_argument('--request',type=Path);p.add_argument('--offline-demo',action='store_true')
    p.add_argument('--device-report-device-id')
    p.add_argument('--seconds',type=int);p.add_argument('command',nargs=argparse.REMAINDER)
    args=p.parse_args(argv);directory=args.run_directory
    from scripts.dev.console_job import join
    join(args.job)
    import ctypes
    ctypes.windll.kernel32.SetConsoleTitleW('AI 监测系统 · '+args.role+' · '+directory.name)
    with (directory/(args.role+'.log')).open('a',encoding='utf8',buffering=1) as log:
        out,err=sys.stdout,sys.stderr;sys.stdout=Tee(out,log);sys.stderr=Tee(err,log)
        code=0;reason='SERVICE_EXITED'
        try:
            write_status(directory,args.role,state='STARTING',code='SERVICE_STARTING',exit_code=None)
            if args.role=='bot':
                from apps.qq_bot.management_cli import run,emit
                def status(c,**fields):
                    nonlocal reason
                    reason=c
                    if c=='MANAGEMENT_BOT_APPROVAL_REQUIRED':state='APPROVAL_REQUIRED'
                    elif c in ('QQ_GATEWAY_READY','QQ_GATEWAY_RESUMED'):state='READY'
                    elif c in ('QQ_GATEWAY_CONNECTING','QQ_GATEWAY_RESUMING','QQ_GATEWAY_IDENTIFYING'):state='CONNECTING'
                    else:state=None
                    if state:write_status(directory,'bot',state=state,code=c,exit_code=None)
                    emit(c,**fields)
                code=run(args.request,directory/'bot-run',offline=args.offline_demo,seconds=args.seconds,
                         stop_requested=lambda:stopped(directory,'bot'),emit_status=status,
                         device_report_device_id=args.device_report_device_id)
            else:
                command=args.command[1:] if args.command[:1]==['--'] else args.command
                expected=str(ROOT/'scripts/dev/local_session.py')
                if '--console-role' not in command or expected not in command:
                    raise RuntimeError('INVALID_STACK_SERVICE_COMMAND')
                role_at=command.index('--console-role')
                if command[role_at+1]!=args.role:raise RuntimeError('INVALID_STACK_SERVICE_COMMAND')
                from scripts.dev.local_session import console_role
                write_status(directory,args.role,state='RUNNING',code='SERVICE_RUNNING',exit_code=None)
                code=console_role(command[role_at+1:])
        except KeyboardInterrupt:reason='SERVICE_INTERRUPTED'
        except BaseException as error:
            import re
            reason=getattr(error,'code',str(error) if isinstance(error,RuntimeError) else 'SERVICE_FAILED')
            if not re.fullmatch('[A-Z][A-Z0-9_]{0,80}',str(reason)):reason='SERVICE_FAILED'
            print(json.dumps({'code':reason}),flush=True);code=1
        finally:
            write_status(directory,args.role,state='EXITED',code=reason,exit_code=code)
            sys.stdout,sys.stderr=out,err
    return code

if __name__=='__main__':raise SystemExit(main())
