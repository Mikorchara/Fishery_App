"""Video + score startup contracts with synthetic instances and zero external I/O."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
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
        self.assertEqual(web[web.index('--demo-video')+1],str(self.video))
        self.assertIn('--assistant-score-trial',web)
        self.assertNotIn('--demo-video',sim);self.assertNotIn('--assistant-score-trial',sim)

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
