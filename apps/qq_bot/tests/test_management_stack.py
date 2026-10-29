"""Real Windows consoles/jobs with synthetic data and Fake QQ/SDK only."""
from contextlib import closing
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from apps.qq_bot.management_cli import initialize_demo
from apps.qq_bot.management_config import ROOT
from scripts.dev.management_stack import preflight,request_stop
from apps.management_web.tests import test_windows_demo_lifecycle as process_fixture


@unittest.skipUnless(os.name=='nt','Windows consoles and jobs')
class ManagementStackTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory(dir=ROOT/'outputs/test-tmp');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.request=initialize_demo(self.root/'instance',self.root/'config',app_id='123456789',
            group_id='stack-test-'+self.root.name,members=('member-test',),enable=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]

    def wait(self,condition,timeout=30):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if condition():return
            time.sleep(.1)
        self.fail('owned stack condition timed out')

    def start(self,*,bot=True,only=False,seconds=70,quarantine=False,interactive=False,menu_input=None):
        log=self.root/'controller.log'
        output=log.open('wb');self.addCleanup(output.close)
        command=[sys.executable,'-X','utf8','-I','-B','-u',str(ROOT/'scripts/dev/management_stack.py'),
            '--request',str(self.request),'--port',str(self.port),'--offline-demo','--no-assistant','--seconds',str(seconds)]
        if interactive:command+=['--interactive-scenario']
        if bot:command+=['--with-bot']
        if only:command+=['--bot-only']
        if quarantine:
            # Test-only instrumentation of the owned Bot child, no product fault switch.
            script=command[command.index(str(ROOT/'scripts/dev/management_stack.py'))]
            args=command[command.index(script)+1:]
            inject='''import sys,subprocess,asyncio
from pathlib import Path
sys.path.insert(0,sys.argv.pop(1))
original=subprocess.Popen
child_code="""import sys
sys.path.insert(0,sys.argv.pop(1))
from apps.qq_bot import demo_runtime
original=demo_runtime.provider_factory
def broken(runtime,remaining):
    client=original(runtime,remaining)
    async def fault(response):
        from apps.ai_backend.sdk_resources import SDK_RESOURCES
        lease=SDK_RESOURCES.reserve();lease.fail('SDK_CLEANUP_FAILED');lease.settle()
    client._client.event_hooks['response'].append(fault)
    return client
demo_runtime.provider_factory=broken
from scripts.dev.stack_console import main
raise SystemExit(main())
"""
def launch(command,**options):
    if '--role' in command and command[command.index('--role')+1]=='bot':
        at=next(i for i,v in enumerate(command) if v.endswith('stack_console.py'))
        command=[*command[:at],'-c',child_code,sys.path[0],*command[at+1:]]
    return original(command,**options)
subprocess.Popen=launch
from scripts.dev.management_stack import main
raise SystemExit(main())'''
            command=[sys.executable,'-X','utf8','-I','-B','-u','-c',inject,str(ROOT),*args]
        if menu_input is not None:
            # Feed the real Simulator console menu only, never the Bot approval.
            script=command.index(str(ROOT/'scripts/dev/management_stack.py'))
            inject='''import sys,subprocess,runpy,asyncio
sys.path.insert(0,sys.argv.pop(1))
answer=sys.argv.pop(1)
original=subprocess.Popen
def launch(command,**options):
    controlled='--role' in command and command[command.index('--role')+1]=='simulator'
    if controlled:options['stdin']=subprocess.PIPE
    child=original(command,**options)
    if controlled:
        child.stdin.write(answer.encode());child.stdin.close()
    return child
subprocess.Popen=launch
script=sys.argv.pop(1);sys.argv[0]=script
runpy.run_path(script,run_name='__main__')'''
            command=[sys.executable,'-X','utf8','-I','-B','-u','-c',inject,str(ROOT),menu_input,*command[script:]]
        child=subprocess.Popen(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        directory=[None]
        def cleanup():
            if directory[0] is not None:request_stop(directory[0],'all')
            try:child.wait(timeout=35)
            except subprocess.TimeoutExpired:
                # Executing controller owns a kill-on-close root job; only kill
                # the PID recorded by this invocation, never scan Python names.
                if directory[0] is not None:
                    pid=json.loads((directory[0]/'stack.json').read_text())['controller_pid']
                    process_fixture.WindowsDemoLifecycleTests.kill_owned(pid)
                if child.poll() is None:child.terminate()
                child.wait(timeout=8)
        self.addCleanup(cleanup)
        def started():
            lines=log.read_text(encoding='utf8',errors='replace').splitlines()
            for line in lines:
                try:value=json.loads(line)
                except ValueError:continue
                if value.get('code')=='STACK_STARTING':directory[0]=Path(value['run_directory']);return True
            return child.poll() is not None
        self.wait(started)
        self.assertIsNotNone(directory[0],log.read_text(encoding='utf8',errors='replace'))
        return child,directory[0]

    def status(self,directory,role):
        try:return json.loads((directory/(role+'.status.json')).read_text(encoding='utf8'))
        except (OSError,ValueError):return {}

    def count(self):
        with closing(sqlite3.connect((self.root/'instance/monitoring.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
            return db.execute('SELECT count(*) FROM batches').fetchone()[0]

    def test_three_consoles_stop_bot_and_duplicate_port_or_instance_do_not_harm_pair(self):
        sentinel=subprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(180)'],creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(lambda:(sentinel.terminate(),sentinel.wait(timeout=5)) if sentinel.poll() is None else None)
        child,directory=self.start()
        self.wait(lambda:self.status(directory,'bot').get('state')=='READY' or child.poll() is not None)
        self.assertIsNone(child.poll(),(directory/'controller.log').read_text())
        records=[self.status(directory,r) for r in ('web','simulator','bot')]
        self.assertEqual(len({r['pid'] for r in records}),3)
        self.assertEqual(len({r['console_hwnd'] for r in records}),3)
        self.assertTrue(all(r['console_hwnd'] for r in records))
        self.wait(lambda:(directory/'bot-run/turn-1.result.json').exists())
        report=json.loads((directory/'bot-run/turn-1.result.json').read_text())
        self.assertTrue(report['verified']);self.assertEqual(report['model_http_requests'],2)
        with self.assertRaisesRegex(Exception,'LOCAL_PORT_IN_USE'):
            preflight(request=self.request,port=self.port,with_bot=True,offline=True)
        # A second writer on another port is rejected by the instance lock.
        with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));another=reserve.getsockname()[1]
        result=subprocess.run([sys.executable,'-X','utf8','-I','-B',str(ROOT/'scripts/dev/management_stack.py'),
            '--request',str(self.request),'--port',str(another),'--no-assistant'],cwd=ROOT,capture_output=True,text=True,encoding='utf8',timeout=15)
        self.assertNotEqual(result.returncode,0);self.assertIn('ALREADY_RUNNING',result.stdout)
        request_stop(directory,'bot')
        self.wait(lambda:self.status(directory,'bot').get('state')=='EXITED')
        before=self.count();self.wait(lambda:self.count()>before,timeout=15)
        self.assertIsNone(child.poll());self.assertIsNone(sentinel.poll())
        self.assertTrue(process_fixture.alive(records[0]['pid']))
        self.assertTrue(process_fixture.alive(records[1]['pid']))
        self.assertTrue((directory/'bot-run/result.json').exists())
        request_stop(directory,'all');child.wait(timeout=30)
        self.wait(lambda:not any(process_fixture.alive(r['pid']) for r in records))
        self.assertIsNone(sentinel.poll())

    def test_bot_crash_cleans_its_job_while_simulator_keeps_writing(self):
        child,directory=self.start()
        self.wait(lambda:self.status(directory,'bot').get('state')=='READY')
        pid=self.status(directory,'bot')['pid']
        process_fixture.WindowsDemoLifecycleTests.kill_owned(pid)
        before=self.count();self.wait(lambda:self.count()>before,timeout=15)
        self.assertIsNone(child.poll())
        self.wait(lambda:'"role": "bot"' in (directory/'controller.log').read_text() and
            '"state": "EXITED"' in (directory/'controller.log').read_text())
        self.assertFalse(process_fixture.alive(pid))

    def test_no_bot_default_and_standalone_bot_exit(self):
        child,directory=self.start(bot=False)
        self.wait(lambda:self.status(directory,'simulator').get('state')=='RUNNING')
        self.assertFalse((directory/'bot.status.json').exists())
        request_stop(directory,'all');child.wait(timeout=30)
        solo,solo_directory=self.start(only=True,seconds=5)
        solo.wait(timeout=25)
        self.assertEqual(solo.returncode,0,(solo_directory/'controller.log').read_text())
        self.assertFalse((solo_directory/'web.status.json').exists())
        self.assertFalse((solo_directory/'simulator.status.json').exists())

    def test_sdk_quarantine_in_bot_process_leaves_web_and_ingestion_alive(self):
        child,directory=self.start(quarantine=True)
        self.wait(lambda:self.status(directory,'bot').get('state')=='EXITED')
        report=json.loads((directory/'bot-run/result.json').read_text())
        self.assertEqual(report['quota']['state'],'HALTED')
        self.assertFalse(report['turns'][0]['verified'])
        before=self.count();self.wait(lambda:self.count()>before,timeout=15)
        self.assertIsNone(child.poll())
        self.assertTrue(process_fixture.alive(self.status(directory,'web')['pid']))

    def test_menu_waits_before_sending_and_zero_stops_owned_stack(self):
        before=self.count()
        child,directory=self.start(interactive=True)
        self.wait(lambda:'请选择模拟场景' in (directory/'simulator.log').read_text(encoding='utf8')
                  if (directory/'simulator.log').exists() else False)
        # Even a full reporting interval must not generate a batch before selection.
        time.sleep(10.5)
        self.assertEqual(self.count(),before)
        self.assertIsNone(child.poll())
        request_stop(directory,'all');child.wait(timeout=30)
        cancelled,cancel_directory=self.start(interactive=True,menu_input='0\n')
        cancelled.wait(timeout=30)
        self.assertEqual(cancelled.returncode,0,(cancel_directory/'controller.log').read_text())
        self.assertEqual(self.count(),before)
        self.assertFalse(any(process_fixture.alive(self.status(cancel_directory,r).get('pid',0))
                             for r in ('web','simulator','bot')))

    def test_menu_invalid_default_and_selected_scenario_with_new_session(self):
        from scripts.dev.local_session import DEMO_SCENARIOS
        for answer,index in [('bad\n\n',0),('7\n',6)]:
            with self.subTest(scenario=DEMO_SCENARIOS[index][0]):
                before=self.count()
                child,directory=self.start(interactive=True,menu_input=answer)
                self.wait(lambda:self.count()>before,timeout=25)
                log=(directory/'simulator.log').read_text(encoding='utf8')
                key,label=DEMO_SCENARIOS[index]
                self.assertIn(f'当前场景：{label} ({key})',log)
                if index==0:self.assertIn('输入无效',log)
                self.assertIsNone(child.poll())
                request_stop(directory,'all');child.wait(timeout=30)
                self.assertEqual(child.returncode,0)

    def test_stack_cli_preserves_noninteractive_default_and_threads_options(self):
        from scripts.dev import management_stack
        with patch.object(management_stack,'launch_stack',return_value=0) as launch:
            self.assertEqual(management_stack.main(['--request',str(self.request),'--with-bot',
                '--scenario','low_oxygen','--interactive-scenario','--open-browser']),0)
            self.assertTrue(launch.call_args.kwargs['interactive_scenario'])
            self.assertTrue(launch.call_args.kwargs['open_browser'])
            self.assertEqual(launch.call_args.kwargs['scenario'],'low_oxygen')
            self.assertEqual(management_stack.main(['--request',str(self.request),'--with-bot',
                '--scenario','low_oxygen']),0)
            self.assertFalse(launch.call_args.kwargs['interactive_scenario'])
        wrapper=(ROOT/'scripts/dev/启动QQ演示系统.cmd').read_text(encoding='utf8')
        self.assertIn('%~dp0Start-ManagementStack.ps1',wrapper)
        self.assertIn('-WithBot -NoAssistant -InteractiveScenario -OpenBrowser',wrapper)
        self.assertNotIn('APPROVE',wrapper)

    def test_powershell_check_missing_config_scope_and_no_network(self):
        command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
            str(ROOT/'scripts/dev/Start-QQBot.ps1'),'-Check','-OfflineDemo','-Request',str(self.request)]
        result=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        self.assertIn(b'MANAGEMENT_QQ_CHECKED_APPROVAL_REQUIRED',result.stdout)
        relative=str(self.request.relative_to(ROOT))
        for entry in ('Start-QQBot.ps1','Start-ManagementStack.ps1'):
            extra=['-WithBot','-InteractiveScenario'] if entry=='Start-ManagementStack.ps1' else []
            checked=subprocess.run(['powershell.exe','-NoProfile','-File',str(ROOT/'scripts/dev'/entry),
                '-Check','-OfflineDemo','-Request',relative,*extra],cwd=ROOT,capture_output=True,timeout=15)
            self.assertEqual(checked.returncode,0,checked.stderr.decode(errors='replace'))
            self.assertIn(b'STACK_PREFLIGHT_OK',checked.stdout)
        invalid=subprocess.run([*command[:-1],str(self.root/'missing.json')],cwd=ROOT,capture_output=True,timeout=15)
        self.assertNotEqual(invalid.returncode,0)
        for name in ('Start-ManagementStack.ps1','Start-QQBot.ps1','Stop-QQBot.ps1','Stop-ManagementStack.ps1'):
            self.assertTrue((ROOT/'scripts/dev'/name).read_bytes().startswith(b'\xef\xbb\xbf'))

    def test_cross_entry_writer_guard_and_legacy_unmarked_default(self):
        from apps.management_process import marked_instance_writer,probe_writer
        with marked_instance_writer(self.root/'instance'):
            with self.assertRaisesRegex(Exception,'MANAGEMENT_INSTANCE_WRITER_ALREADY_RUNNING'):
                preflight(request=self.request,port=self.port,with_bot=True,offline=True)
        probe_writer(self.root/'instance')
        unmarked=self.root/'unmarked';unmarked.mkdir()
        with marked_instance_writer(unmarked):pass
        self.assertEqual(list(unmarked.iterdir()),[])
