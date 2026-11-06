import argparse
import io
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
from scripts.dev.device_mode import select_mode
from scripts.dev import local_session,management_stack
from apps.device_reports.binding import validate_binding


class ModeTests(unittest.TestCase):
    def test_menu_and_offline_check(self):
        for choice, expected in [('1','full'),('2','water-only'),('','full')]:
            args=argparse.Namespace(interactive_mode=True,check=False,simulation_mode='full',device_report_directory=None,device_report_device_id=None)
            with patch('builtins.input',return_value=choice),patch('sys.stdout',new=io.StringIO()):
                self.assertTrue(select_mode(args))
            self.assertEqual(args.simulation_mode,expected)
        args.check=True
        with patch('builtins.input',side_effect=AssertionError('check must not prompt')):
            self.assertTrue(select_mode(args))

    def test_binding_rejects_conflicts(self):
        for mode,directory,device in [('full',Path('reports'),'board'),('water-only',None,'board'),('water-only',Path('reports'),None)]:
            with self.assertRaises(ValueError):validate_binding(mode,directory,device)

    def test_stack_forwards_mode_without_launching_or_network(self):
        with patch.object(management_stack,'launch_stack',return_value=0) as launch:
            self.assertEqual(management_stack.main(['--simulation-mode','water-only','--device-report-directory',str(Path.cwd()/'outputs/synthetic-report-placeholder'),'--device-report-device-id','board']),0)
        self.assertEqual(launch.call_args.kwargs['simulation_mode'],'water-only')
        self.assertEqual(launch.call_args.kwargs['device_report_device_id'],'board')

    def test_all_four_shortcuts_offer_mode_selection(self):
        root=Path(__file__).resolve().parents[3]
        for name in ('启动演示系统.cmd','启动视频演示系统.cmd','启动QQ演示系统.cmd','启动QQ视频演示系统.cmd'):
            self.assertIn('-InteractiveMode',(root/'scripts/dev'/name).read_text(encoding='utf-8'))

    def test_shortcut_mode_two_binds_fixed_reports_without_database_or_initialization(self):
        root=Path(__file__).resolve().parents[3]
        args=argparse.Namespace(interactive_mode=True,check=False,auto_device_reports=True,
            simulation_mode='full',device_report_directory=None,device_report_device_id=None)
        with patch('builtins.input',return_value='2'),patch('sys.stdout',new=io.StringIO()),\
             patch('sqlite3.connect',side_effect=AssertionError('no database access')),\
             patch('apps.device_reports.storage.ReportStore.initialize',side_effect=AssertionError('no initialization')),\
             patch('socket.socket',side_effect=AssertionError('no listener')):
            self.assertTrue(select_mode(args))
        self.assertEqual(args.simulation_mode,'water-only')
        self.assertEqual(args.device_report_directory,root/'outputs/device-reports')
        self.assertEqual(args.device_report_device_id,'fish-monitor-orin-01')

    def test_shortcut_mode_one_and_default_never_bind_reports(self):
        for choice in ('1',''):
            args=argparse.Namespace(interactive_mode=True,check=False,auto_device_reports=True,
                simulation_mode='water-only',device_report_directory=None,device_report_device_id=None)
            with self.subTest(choice=choice),patch('builtins.input',return_value=choice),\
                 patch('sys.stdout',new=io.StringIO()):
                self.assertTrue(select_mode(args))
            self.assertEqual(args.simulation_mode,'full')
            self.assertIsNone(args.device_report_directory)
            self.assertIsNone(args.device_report_device_id)

    def test_automatic_binding_preserves_explicit_settings_and_refuses_partial_settings(self):
        custom=Path(__file__).resolve().parents[3]/'outputs/synthetic-custom-report-placeholder'
        args=argparse.Namespace(interactive_mode=False,check=False,auto_device_reports=True,
            simulation_mode='water-only',device_report_directory=custom,device_report_device_id='custom-board')
        self.assertTrue(select_mode(args))
        self.assertEqual(args.device_report_directory,custom)
        self.assertEqual(args.device_report_device_id,'custom-board')
        for directory,device in ((custom,None),(None,'custom-board')):
            args=argparse.Namespace(interactive_mode=False,check=False,auto_device_reports=True,
                simulation_mode='water-only',device_report_directory=directory,device_report_device_id=device)
            with self.subTest(directory=directory,device=device),self.assertRaisesRegex(ValueError,'DEVICE_REPORT_BINDING_REQUIRED'):
                select_mode(args)
        args.device_report_directory=custom
        args.device_report_device_id='custom-board'
        args.simulation_mode='full'
        with self.assertRaisesRegex(ValueError,'DEVICE_REPORT_BINDING_REQUIRED'):select_mode(args)

    def test_manual_water_only_still_works_without_automatic_report_binding(self):
        args=argparse.Namespace(interactive_mode=False,check=False,auto_device_reports=False,
            simulation_mode='water-only',device_report_directory=None,device_report_device_id=None)
        with patch('sys.stdout',new=io.StringIO()) as output:self.assertTrue(select_mode(args))
        self.assertIsNone(args.device_report_directory)
        self.assertIsNone(args.device_report_device_id)
        self.assertIn('尚未绑定设备报告',output.getvalue())

    def test_stack_menu_and_offline_check_forward_automatic_binding(self):
        root=Path(__file__).resolve().parents[3]
        with patch.object(management_stack,'launch_stack',return_value=0) as launch,\
             patch('builtins.input',return_value='2'),patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(management_stack.main(['--interactive-mode','--auto-device-reports']),0)
        self.assertEqual(launch.call_args.kwargs['simulation_mode'],'water-only')
        self.assertEqual(launch.call_args.kwargs['device_report_directory'],root/'outputs/device-reports')
        self.assertEqual(launch.call_args.kwargs['device_report_device_id'],'fish-monitor-orin-01')
        with patch.object(management_stack,'preflight',return_value=(root,None)) as preflight,\
             patch('builtins.input',side_effect=AssertionError('check must not prompt')),\
             patch('sqlite3.connect',side_effect=AssertionError('no database')),\
             patch('socket.socket',side_effect=AssertionError('no network')),\
             patch('sys.stdout',new=io.StringIO()) as output:
            self.assertEqual(management_stack.main(['--check','--interactive-mode','--simulation-mode','water-only',
                '--auto-device-reports']),0)
        checked=json.loads(output.getvalue().strip().splitlines()[-1])
        self.assertTrue(checked['device_reports_bound'])
        self.assertEqual(preflight.call_args.kwargs['device_report_device_id'],'fish-monitor-orin-01')

    def test_two_terminal_python_entry_forwards_automatic_binding_without_real_launch(self):
        root=Path(__file__).resolve().parents[3]
        with patch.object(local_session,'run_local',return_value=0) as launch,\
             patch.object(local_session,'require_free_port'),\
             patch.object(Path,'mkdir'),patch('sqlite3.connect',side_effect=AssertionError('no database')),\
             patch('socket.socket',side_effect=AssertionError('no network')),\
             patch('sys.stdout',new=io.StringIO()):
            self.assertEqual(local_session.main(['--simulation-mode','water-only','--auto-device-reports']),0)
        self.assertEqual(launch.call_args.kwargs['simulation_mode'],'water-only')
        self.assertEqual(launch.call_args.kwargs['device_report_directory'],root/'outputs/device-reports')
        self.assertEqual(launch.call_args.kwargs['device_report_device_id'],'fish-monitor-orin-01')

    def test_four_shortcuts_enable_auto_binding_and_detached_powershell_preserves_it(self):
        root=Path(__file__).resolve().parents[3]
        for name in ('启动演示系统.cmd','启动视频演示系统.cmd','启动QQ演示系统.cmd','启动QQ视频演示系统.cmd'):
            with self.subTest(shortcut=name):
                self.assertIn('-AutoDeviceReports',(root/'scripts/dev'/name).read_text(encoding='utf-8'))
        shell=shutil.which('powershell.exe') or shutil.which('pwsh') or shutil.which('powershell')
        if shell is None:self.skipTest('PowerShell is required for this Windows entry point')
        literal="'"+str(root/'scripts/dev/run_local.ps1').replace("'","''")+"'"
        command=("function Read-Host { return '2' }; "
            "function Start-Process { [CmdletBinding()]param([string]$FilePath,[string[]]$ArgumentList,[string]$WindowStyle) "
            "[Console]::WriteLine((@{arguments=$ArgumentList;window_style=$WindowStyle}|ConvertTo-Json -Compress)) }; "
            "& "+literal+" -InteractiveMode -AutoDeviceReports -Detach")
        process=subprocess.run([shell,'-NoProfile','-ExecutionPolicy','Bypass','-Command',command],
            cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
        self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        captured=json.loads(process.stdout.strip())
        self.assertIn('-AutoDeviceReports',captured['arguments'])
        self.assertNotIn('-InteractiveMode',captured['arguments'])
        self.assertEqual(captured['arguments'][captured['arguments'].index('-SimulationMode')+1],'water-only')
        self.assertEqual(captured['window_style'],'Hidden')

    def test_device_receiver_powershell_check_keeps_auth_selection_offline(self):
        root=Path(__file__).resolve().parents[3]
        shell=shutil.which('pwsh') or shutil.which('powershell')
        if shell is None:self.skipTest('PowerShell is required for this Windows entry point')
        script=root/'scripts/dev/Start-DeviceReports.ps1'
        statuses=[]
        for extra in ([],['-RequireToken']):
            process=subprocess.run([shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),
                '-Check','-Directory',str(root/'outputs/synthetic-device-check-unused'),*extra],
                cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(process.returncode,0,process.stdout+process.stderr)
            status=json.loads(process.stdout.strip())
            self.assertEqual(status['code'],'DEVICE_REPORT_CONFIG_CHECKED')
            self.assertFalse(status['database_opened'])
            self.assertFalse(status['credential_checked'])
            self.assertEqual(status['network_requests'],0)
            statuses.append(status)
        self.assertEqual([status['auth_mode'] for status in statuses],['NONE_LAN','TOKEN'])
        self.assertFalse((root/'outputs/synthetic-device-check-unused').exists())
