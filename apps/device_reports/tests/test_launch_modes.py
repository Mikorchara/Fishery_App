import argparse
import io
from pathlib import Path
import unittest
from unittest.mock import patch
from scripts.dev.device_mode import select_mode
from scripts.dev import management_stack
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
