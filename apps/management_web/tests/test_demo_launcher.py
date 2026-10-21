"""Demo data isolation and real Fake SDK knowledge reads; never open user stores."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.management_paths import ManagementPaths
from apps.management_web.instance import initialize_instance
from apps.knowledge.repository import KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
from apps.knowledge.tests.support import seed
from scripts.dev.demo_instance import prepare_demo, knowledge_facts
from apps.ai_service.business_tools.registry import HISTORY_CANDIDATE_TOOL_NAMES


@unittest.skipUnless(os.name == 'nt', 'Windows demo bootstrap')
class DemoDataTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root/'formal'/'knowledge.sqlite3'
        seed(self.source)
        KnowledgeContentService(KnowledgeRepository(self.source)).create({
            'title':'隔离用户知识', 'category':'演示夹具', 'body':'用户添加的独立背景资料，用于验证完整复制。'})
        self.original = self.source.read_bytes()

    def test_first_copy_preserves_every_row_empty_monitoring_and_fresh_policy(self):
        # Decoys must never be copied from the formal directory.
        for name in ('settings.json', 'monitoring.sqlite3', '.env'):
            (self.source.parent/name).write_text('fictional-do-not-copy')
        paths, created, count = prepare_demo(self.root, source=self.source)
        self.assertTrue(created)
        self.assertEqual(count, 32)
        self.assertEqual(knowledge_facts(paths.knowledge), knowledge_facts(self.source))
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(paths.settings.exists())
        self.assertFalse((paths.data_root/'.env').exists())
        self.assertFalse((paths.policy_directory/'tool_policies.json').exists())
        policy = json.loads((paths.policy_directory/'management_assistant_policy.json').read_text())
        self.assertEqual(policy['selected_tools'], list(HISTORY_CANDIDATE_TOOL_NAMES))
        self.assertEqual(policy['generation'], 1)
        with closing(sqlite3.connect(paths.monitoring)) as db:
            for table in ('batches', 'history', 'current', 'events', 'alerts', 'channel_contacts'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)
        content = KnowledgeContentService(KnowledgeRepository(paths.knowledge, require_existing=True))
        self.assertTrue(content.search('鳗鲡低氧表现'))
        self.assertEqual(content.list()['total'], 32)

    def test_reuse_keeps_edits_settings_policy_and_never_opens_formal_source(self):
        paths, _, _ = prepare_demo(self.root, source=self.source)
        content = KnowledgeContentService(KnowledgeRepository(paths.knowledge, require_existing=True))
        content.create({'title':'演示编辑', 'category':'演示', 'body':'演示实例中的独立知识，不属于正式库。'})
        paths.settings.write_text('{"demo":"keep"}')
        policy = paths.policy_directory/'management_assistant_policy.json'
        value = json.loads(policy.read_text()); value['selected_tools'] = []
        policy.write_text(json.dumps(value))
        before = {p:hashlib.sha256(p.read_bytes()).digest() for p in paths.data_root.rglob('*') if p.is_file()}
        with patch('scripts.dev.demo_instance.frozen_knowledge', side_effect=AssertionError('source must not open')):
            _, created, count = prepare_demo(self.root, source=self.root/'missing-source.sqlite3')
        self.assertFalse(created); self.assertEqual(count, 33)
        self.assertEqual({p:hashlib.sha256(p.read_bytes()).digest() for p in before}, before)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_existing_empty_or_incomplete_instance_refuses_without_repair(self):
        (self.root/'outputs').mkdir()
        paths = ManagementPaths.resolve(self.root, data_root=self.root/'outputs/demo-instance')
        initialize_instance(paths)
        before = paths.knowledge.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'DEMO_KNOWLEDGE_EMPTY_REQUIRES_REVIEW'):
            prepare_demo(self.root, source=self.source)
        self.assertEqual(paths.knowledge.read_bytes(), before)
        paths.monitoring.unlink()  # Disposable fixture only.
        with self.assertRaisesRegex(ValueError, 'MONITORING_DATABASE_MISSING'):
            prepare_demo(self.root, source=self.source)
        self.assertFalse(paths.monitoring.exists())

    def test_busy_source_refuses_before_publishing_or_touching_source(self):
        from scripts.dev.demo_instance import frozen_knowledge
        # Persistent SQLite logs need review; do not silently checkpoint/delete.
        sidecar = Path(str(self.source)+'-wal')
        sidecar.write_bytes(b'fixture-log')
        with self.assertRaisesRegex(RuntimeError, 'DEMO_SOURCE_BUSY_CLOSE_FORMAL_WEB'):
            prepare_demo(self.root, source=self.source)
        self.assertEqual(sidecar.read_bytes(), b'fixture-log')
        self.assertFalse((self.root/'outputs/demo-instance').exists())
        sidecar.unlink()
        with frozen_knowledge(self.source):
            with self.assertRaises(OSError):
                self.source.open('r+b')
        self.assertEqual(self.source.read_bytes(), self.original)


@unittest.skipUnless(os.name == 'nt', 'Windows demo bootstrap')
class DemoAITests(unittest.TestCase):
    def test_normal_and_streaming_fake_sdk_use_demo_knowledge_and_existing_scopes(self):
        # Reuse the established socket guard, Fake SDK and HTTP/SSE driver.
        from apps.ai_service.tests.test_unified_tools import UnifiedToolsTests, KNOWLEDGE
        from apps.ai_backend.openai_compatible_adapter import OpenAICompatibleAdapter
        from apps.ai_service.service import ManagementAssistantService
        from apps.management_web.ai_adapter import ManagementAssistant
        from apps.management_web.app import create_app
        fixture = UnifiedToolsTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.configure()
        source = fixture.root/'formal'/'knowledge.sqlite3'
        seed(source)
        paths, _, _ = prepare_demo(fixture.root, source=source)
        content = KnowledgeContentService(KnowledgeRepository(paths.knowledge, require_existing=True))
        old = fixture.backend
        fixture.backend = ManagementAssistantService(fixture.monitoring, knowledge=content,
            credentials=old.credentials, traces=old.traces, policy_directory=paths.policy_directory,
            gateway_factory=lambda:OpenAICompatibleAdapter(async_client_factory=fixture.sdk.factory),
            execution_config=old._execution_config, streaming_config=old._streaming_config,
            unified_config=old._unified_config)
        fixture.web = ManagementAssistant(fixture.backend)
        fixture.client = create_app(data_service=fixture.monitoring, ai=fixture.web, knowledge_service=content).test_client()
        fixture.headers = {'X-Management-AI':fixture.web.browser_token}
        for streaming in (False, True):
            with self.subTest(streaming=streaming):
                result = fixture.send((KNOWLEDGE,), streaming)
                self.assertTrue(result['successful_turn'], result)
                mode = 'streaming' if streaming else 'execution'
                self.assertEqual(fixture.config['presets'][0][mode]['release_status'], 'local_experimental')
                self.assertEqual([d['function']['name'] for d in fixture.sdk.bodies[0]['tools']], list(HISTORY_CANDIDATE_TOOL_NAMES))
                payload = json.loads(next(m['content'] for m in fixture.sdk.bodies[1]['messages'] if m['role']=='tool'))
                self.assertEqual(payload['status'], 'OK')
                self.assertGreater(payload['result_count'], 0)
                ids = {item.evidence_id for item in content.search('鳗鲡低氧表现', top_k=3)}
                self.assertTrue({item['id'] for item in payload['evidence']} <= ids)
        # Revoking knowledge in the demo policy must remain effective on restart.
        fixture.policy([HISTORY_CANDIDATE_TOOL_NAMES[0]])
        prepare_demo(fixture.root, source=fixture.root/'missing.sqlite3')
        result = fixture.send((KNOWLEDGE,))
        self.assertFalse(result['successful_turn'])
        self.assertEqual(result['error_code'], 'TOOL_NOT_ALLOWED')
        self.assertEqual(len(fixture.sdk.bodies), 1)
