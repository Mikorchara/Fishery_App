"""Allowlisted Management staging, imported in a fresh isolated Python process."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

from scripts.packaging.prepare_management import prepare

ROOT = Path(__file__).resolve().parents[3]


class PackagingBoundaryTests(unittest.TestCase):
    def test_management_stage_contains_only_owned_code_and_candidate(self):
        target = ROOT/'outputs/test-tmp'/('m2-stage-'+uuid.uuid4().hex)
        stage = prepare(target)
        for name in ('qq_bot/hybrid_run.py', 'qq_bot/monitoring_source.py',
                     'ai_backend/sdk_resources.py', 'ai_service/channel_hybrid.py',
                     'management_web/demo_video.py', 'ai_service/score_execution.py',
                     'ai_service/business_tools/water_quality_score.py',
                     'ai_service/resources/assistant_score_trial.json'):
            self.assertTrue((stage/'apps'/name).is_file())
        for name in ('启动视频演示系统.cmd','启动QQ视频演示系统.cmd'):
            self.assertTrue((stage/'scripts/dev'/name).is_file())
        self.assertFalse((stage/'sample.mp4').exists())
        for path in stage.rglob('*'):
            self.assertNotIn(path.suffix, ('.sqlite3', '.db', '.env', '.jsonl'))
            self.assertNotIn('tests', path.relative_to(stage).parts)
        code = '''
import importlib,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
root=Path(sys.argv[1])
for name in ('apps.qq_bot.hybrid_run','apps.qq_bot.gateway','apps.ai_service.service','apps.monitoring.repository',
             'apps.management_web.demo_video','apps.ai_service.score_execution'):
    module=importlib.import_module(name)
    assert Path(module.__file__).is_relative_to(root)
assert not any(n=='fishery_ai' or n.startswith('fishery_ai.') for n in sys.modules)
from apps.ai_service.channel_hybrid import candidate_record,prepared_scope
from apps.qq_bot.conversations import ConversationOptions
expected=candidate_record(prepared_scope(ConversationOptions(trigger_mode='mention_ai',memory_enabled=True)))
assert json.loads((root/'apps/ai_service/resources/management_qq_hybrid_candidate.json').read_text())==expected
from apps.qq_bot.__main__ import main
main(['--check'])
'''
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(stage)],
                                cwd=stage, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['code'], 'M2_QQ_BOT_DISABLED')
