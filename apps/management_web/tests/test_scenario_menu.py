"""Offline menu/CLI coverage; never opens credentials, user data or a Provider."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from apps.simulator.scenarios import SCENARIOS
from scripts.dev import local_session as entry


class ScenarioMenuTests(unittest.TestCase):
    def test_numbered_labels_map_to_simulator_scenarios(self):
        self.assertEqual([key for key, _ in entry.DEMO_SCENARIOS], [
            'normal', 'low_oxygen', 'suspected_disease', 'reduced_feeding',
            'combined_anomaly', 'device_offline', 'oxygen_drop_recovery', 'device_visual_recovery'])
        for index, (key, label) in zip((1, 2, 3, 4, 5, 6, 7, 9), entry.DEMO_SCENARIOS):
            self.assertIn(key, SCENARIOS)
            output = []
            self.assertEqual(entry.choose_scenario(read=lambda _:str(index), emit=output.append), (key, label))
            self.assertTrue(any(label in line and key in line for line in output))

    def test_device_mode_hides_visual_demo_and_keeps_numbering(self):
        answers = iter(['9', '7']); output = []
        self.assertEqual(entry.choose_scenario(read=lambda _:next(answers), emit=output.append, water_only=True),
                         ('oxygen_drop_recovery', '溶解氧快速下降后逐步回升'))
        self.assertFalse(any('device_visual_recovery' in line for line in output))
        self.assertEqual(sum('输入无效' in line for line in output), 1)
        self.assertIsNone(entry.choose_scenario(read=lambda _:'8', emit=lambda _:None, water_only=True))

    def test_enter_default_invalid_retry_and_exit(self):
        for final, expected in [('', entry.DEMO_SCENARIOS[0]), ('2', entry.DEMO_SCENARIOS[1]), ('0', None), ('8', None)]:
            with self.subTest(final=final):
                answers = iter(['no', '99', '-1', final]); output = []
                choice = entry.choose_scenario(read=lambda _:next(answers), emit=output.append)
                self.assertEqual(choice, expected)
                self.assertEqual(sum('输入无效' in line for line in output), 3)
        for error in (EOFError, KeyboardInterrupt):
            with self.subTest(error=error):
                def stopped(_):raise error()
                self.assertIsNone(entry.choose_scenario(read=stopped, emit=lambda _:None))

    def test_interactive_flag_requires_visible_terminals_before_storage_or_processes(self):
        with patch.object(entry, 'run_local') as run, self.assertRaises(SystemExit) as error:
            entry.main(['--interactive-scenario'])
        self.assertEqual(error.exception.code, 2); run.assert_not_called()
        with patch.object(entry, 'require_free_port') as probe, self.assertRaisesRegex(
                RuntimeError, 'LOCAL_SCENARIO_MENU_REQUIRES_TERMINALS'):
            entry.run_local(interactive_scenario=True)
        probe.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows console wrapper')
    def test_real_console_wrapper_input_runs_dry_scenarios_and_cancels_without_send(self):
        command = [sys.executable, '-X', 'utf8', '-I', '-B', '-u', str(Path(entry.__file__)),
            '--console-role', 'simulator', '--interactive-scenario', '--', '-m', 'apps.simulator',
            '--scenario', 'normal', '--server', 'http://127.0.0.1:8766', '--interval', '10', '--dry-run', '--windows', '1']
        for number, (scenario, label) in zip((1, 2, 3, 4, 5, 6, 7, 9), entry.DEMO_SCENARIOS):
            with self.subTest(scenario=scenario):
                result = subprocess.run(command, input=str(number)+'\n', text=True, encoding='utf-8',
                    cwd=entry.ROOT, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'当前场景：{label} ({scenario})', result.stdout)
                self.assertIn('window 1: dry-run', result.stdout)
        for answer in ('0\n', '8\n', ''):
            with self.subTest(cancel=answer):
                result = subprocess.run(command, input=answer, text=True, encoding='utf-8',
                    cwd=entry.ROOT, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('window 1:', result.stdout)
                self.assertIn('已取消模拟', result.stdout)

    def test_double_click_opts_in_but_regular_powershell_does_not(self):
        script = (entry.ROOT/'scripts/dev/run_local.ps1').read_bytes()
        self.assertTrue(script.startswith(b'\xef\xbb\xbf'))
        script = script.decode('utf-8-sig')
        self.assertIn('[switch]$InteractiveScenario', script)
        self.assertIn("if ($InteractiveScenario) { $launchArgs += '--interactive-scenario' }", script)
        self.assertIn("'ShowTerminals','InteractiveScenario','OpenBrowser'", script)
        self.assertIn("'device_visual_recovery')]", script)
        command = (entry.ROOT/'scripts/dev/启动演示系统.cmd').read_text()
        self.assertIn('-ShowTerminals -InteractiveScenario -OpenBrowser -Detach', command)
        for scenario, _ in entry.DEMO_SCENARIOS:
            server, simulator = entry.commands('python', scenario, 8766, 42)
            self.assertEqual(simulator[simulator.index('--scenario')+1], scenario)
            self.assertNotIn('--interactive-scenario', server+simulator)
