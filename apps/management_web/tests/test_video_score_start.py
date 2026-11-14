"""Video + score startup contracts with synthetic instances and zero external I/O."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.dev import management_stack as stack,local_session
from apps.qq_bot.management_cli import initialize_demo
from apps.qq_bot.management_config import ROOT


class VideoScoreStartTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory(dir=ROOT/'outputs/test-tmp');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.video=self.root/'sample.mp4';self.video.write_bytes(b'\x00\x00\x00\x18ftypisom'+b'fictional-video'*20)

    def test_four_shortcuts_preserve_old_defaults_and_new_video_enables_web_score(self):
        for name in ('启动视频演示系统.cmd','启动QQ视频演示系统.cmd'):
            text=(ROOT/'scripts/dev'/name).read_text(encoding='utf8')
            self.assertIn('if not exist',text);self.assertIn('sample.mp4',text)
            self.assertIn('-DemoVideo',text);self.assertIn('-ScoreTrial',text)
            self.assertIn('-EventTrial',text)
            self.assertIn('-InteractiveScenario',text);self.assertNotIn('-NoAssistant',text)
        for name in ('启动演示系统.cmd','启动QQ演示系统.cmd'):
            text=(ROOT/'scripts/dev'/name).read_text(encoding='utf8')
            self.assertNotIn('-DemoVideo',text);self.assertNotIn('-ScoreTrial',text)
        self.assertIn('-EventTrial',(ROOT/'scripts/dev/启动演示系统.cmd').read_text(encoding='utf8'))
        qq_without_web_ai=(ROOT/'scripts/dev/启动QQ演示系统.cmd').read_text(encoding='utf8')
        self.assertIn('-NoAssistant',qq_without_web_ai)
        self.assertNotIn('-EventTrial',qq_without_web_ai)

    def test_stack_forwards_video_and_score_without_starting_services(self):
        with patch.object(stack,'launch_stack',return_value=0) as launch:
            self.assertEqual(stack.main(['--demo-video',str(self.video),'--score-trial']),0)
        self.assertEqual(launch.call_args.kwargs['demo_video'],self.video)
        self.assertTrue(launch.call_args.kwargs['score_trial'])
        web,sim=local_session.commands('python','normal',8766,42,demo_video=self.video,score_trial=True)
        self.assertEqual(web[1:3], ['-m', 'apps.management_web'])
        self.assertEqual(web[web.index('--demo-video')+1],str(self.video))
        self.assertIn('--assistant-score-trial',web)
        self.assertNotIn('--demo-video',sim);self.assertNotIn('--assistant-score-trial',sim)

    def test_board_video_launch_targets_only_web_in_device_mode(self):
        source='rtsp://127.0.0.1:8554/test.264'
        with patch.object(stack,'launch_stack',return_value=0) as launch:
            self.assertEqual(stack.main(['--simulation-mode','water-only','--board-video',source]),0)
        self.assertEqual(launch.call_args.kwargs['board_video'],source)
        self.assertEqual(launch.call_args.kwargs['simulation_mode'],'water-only')
        web,sim=local_session.commands('python','normal',8766,42,simulation_mode='water-only',board_video=source)
        self.assertEqual(web[1:3], ['-m', 'apps.management_web.board_video_entry'])
        self.assertEqual(web[web.index('--board-video')+1],source)
        self.assertNotIn('--demo-video',web)
        self.assertNotIn('--board-video',sim)
        self.assertNotIn(source,sim)

    def test_visible_web_console_dispatches_the_opt_in_board_module(self):
        args = ['--port', '8767', '--simulation-mode', 'water-only',
                '--board-video', 'rtsp://127.0.0.1:8554/test.264']
        with patch('ctypes.windll'), patch('runpy.run_module') as run, patch.object(sys, 'argv', []):
            self.assertEqual(local_session.console_role([
                'web', '--', '-m', 'apps.management_web.board_video_entry', *args,
            ]), 0)
            run.assert_called_once_with('apps.management_web.board_video_entry', run_name='__main__', alter_sys=True)
            self.assertEqual(sys.argv, ['apps.management_web.board_video_entry', *args])

    def test_fifth_shortcut_asks_for_the_current_board_address_and_launches_the_qq_stack(self):
        scripts=self.root/'scripts/dev'
        scripts.mkdir(parents=True)
        name='启动QQ板端视频演示系统.cmd'
        for filename in (name,'Start-BoardVideoDemo.ps1'):
            shutil.copyfile(ROOT/'scripts/dev'/filename,scripts/filename)
        # Exercise the actual CMD and its prompt without opening consoles or using QQ.
        (scripts/'Start-ManagementStack.ps1').write_text(
            "param($Request,[switch]$WithBot,$SimulationMode,[switch]$AutoDeviceReports,"
            "$BoardVideo,[switch]$InteractiveScenario,[switch]$OpenBrowser,[switch]$ScoreTrial,[switch]$EventTrial)\n"
            "ConvertTo-Json -Compress -InputObject $PSBoundParameters\n", encoding='ascii')
        (scripts/'ffmpeg.cmd').write_text('@exit /b 0\n',encoding='ascii')
        command=['cmd.exe','/d','/c',name]
        for text, expected in (
            (b'\r\n192.168.2.220\r\n','rtsp://192.168.2.220:554/normal.264'),
            (b'rtsp://192.168.68.178:8554/other.264\r\n','rtsp://192.168.68.178:8554/other.264'),
        ):
            with self.subTest(source=expected):
                result=subprocess.run(command,cwd=scripts,input=text,capture_output=True,timeout=15)
                self.assertEqual(result.returncode,0,result.stderr)
                flags=json.loads(result.stdout.splitlines()[-1])
                self.assertEqual(flags['BoardVideo'],expected)
                self.assertEqual(flags['SimulationMode'],'water-only')
                self.assertEqual(Path(flags['Request']),self.root/'outputs/qq-m3-real-config/request.json')
                for flag in ('WithBot','AutoDeviceReports','InteractiveScenario','OpenBrowser','ScoreTrial','EventTrial'):
                    self.assertTrue(flags[flag])
        cancelled=subprocess.run(command,cwd=scripts,input=b'0\r\n',capture_output=True,timeout=15)
        self.assertEqual(cancelled.returncode,0,cancelled.stderr)
        self.assertNotIn(b'"WithBot"',cancelled.stdout)

    def test_board_video_rejects_unusable_startup_combinations(self):
        source='rtsp://127.0.0.1:8554/test.264'
        with self.assertRaisesRegex(RuntimeError,'BOARD_VIDEO_REQUIRES_DEVICE_MODE'):
            local_session.commands('python','normal',8766,42,board_video=source)
        with self.assertRaisesRegex(RuntimeError,'VIDEO_SOURCE_CONFLICT'):
            local_session.commands('python','normal',8766,42,simulation_mode='water-only',
                                   board_video=source,demo_video=self.video)
        with self.assertRaisesRegex(RuntimeError,'BOARD_VIDEO_REQUIRES_WEB'):
            stack.preflight(simulation_mode='water-only',board_video=source,bot_only=True)

    def test_check_uses_explicit_synthetic_request_without_db_keys_network(self):
        request=initialize_demo(self.root/'instance',self.root/'config',app_id='123456789',
            group_id='fictional-video-group',members=('fictional-member',),enable=True)
        with patch('sqlite3.connect',side_effect=AssertionError('database')),\
             patch('apps.ai_backend.credentials.CredentialStore.resolve',side_effect=AssertionError('key')),\
             patch('socket.getaddrinfo',side_effect=AssertionError('network')),\
             patch('socket.socket.connect',side_effect=AssertionError('network')),redirect_stdout(StringIO()) as out:
            result=stack.main(['--request',str(request),'--check','--bot-only','--offline-demo',
                               '--demo-video',str(self.video),'--score-trial'])
        self.assertEqual(result,0);value=json.loads(out.getvalue())
        self.assertTrue(value['video_enabled']);self.assertTrue(value['score_trial_enabled'])
        self.assertFalse(value['summary']['credential_checked']);self.assertFalse(value['summary']['database_opened'])
        self.assertEqual(value['summary']['network_requests'],0)

    def test_invalid_media_and_inconsistent_assistant_fail_before_instance_read(self):
        with patch('apps.qq_bot.management_config.check_request',side_effect=AssertionError('request')):
            with self.assertRaisesRegex(ValueError,'LOCAL_DEMO_MP4_REQUIRED'):
                stack.preflight(with_bot=True,demo_video=self.root/'missing.mp4')
            with self.assertRaisesRegex(RuntimeError,'SCORE_TRIAL_REQUIRES_ASSISTANT'):
                stack.preflight(with_bot=True,score_trial=True,no_assistant=True)
            with self.assertRaisesRegex(RuntimeError,'EVENT_TRIAL_REQUIRES_ASSISTANT'):
                stack.preflight(with_bot=True,event_trial=True,no_assistant=True)

    def test_powershell_parse_bom_and_detach_argument_relay(self):
        for name in ('run_local.ps1','Start-ManagementStack.ps1'):
            path=ROOT/'scripts/dev'/name;self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
            literal="'"+str(path).replace("'","''")+"'"
            command='$errors=$null; $tokens=$null; [System.Management.Automation.Language.Parser]::ParseFile('+literal+',[ref]$tokens,[ref]$errors) | Out-Null; if ($errors.Count) { exit 1 }'
            result=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-Command',command],
                                  capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
        text=(ROOT/'scripts/dev/run_local.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("'UserData','ScoreTrial'",text)
        self.assertIn("'ScoreTrial','EventTrial','EventBoardReports'",text)
        self.assertIn("$detachedArgs += @('-DemoVideo'",text)
        self.assertIn('GetUnresolvedProviderPathFromPSPath($DemoVideo)',text)
