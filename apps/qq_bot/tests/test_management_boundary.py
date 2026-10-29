"""Management-owned offline boundaries; no existing instance, credential or network."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock

import httpx
from apps.ai_service.service import ManagementAssistantService
from apps.ai_service.channel_hybrid import candidate_record, prepared_scope, CONTRACT
from apps.ai_service.channel_session_run import memory_sdk_factory
from apps.ai_service.channel_trial import TrialQwenAdapter
from apps.qq_bot.__main__ import main
from apps.qq_bot.contracts import BotError, GroupAccess
from apps.qq_bot.conversations import ConversationOptions
from apps.qq_bot.monitoring_source import InstanceMonitoring, MonitoringSourceConfig
from apps.qq_bot.transport import QQAPI, connect_gateway, gateway_url
from apps.qq_bot.tests import fixtures

ROOT = Path(__file__).resolve().parents[3]


class ManagementBoundaryTests(unittest.TestCase):
    def test_default_and_check_do_not_open_database_keys_or_network(self):
        for argv in ([], ['--check']):
            with (self.subTest(argv=argv), patch('sqlite3.connect', side_effect=AssertionError('database')),
                 patch('apps.ai_backend.credentials.CredentialStore.resolve', side_effect=AssertionError('key')),
                 patch('socket.getaddrinfo', side_effect=AssertionError('network'))):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(argv), 0)
                report = json.loads(output.getvalue())
                self.assertEqual(report['code'], 'M2_QQ_BOT_DISABLED')
                self.assertFalse(report['network_enabled'])
                self.assertFalse(report['ai_enabled'])

    def test_provider_and_qq_default_network_paths_reject(self):
        with patch('socket.getaddrinfo', side_effect=AssertionError('network')):
            with self.assertRaisesRegex(BotError, 'M2_QQ_NETWORK_DISABLED'):
                QQAPI('123456789', lambda: None)
            with self.assertRaisesRegex(BotError, 'M2_QQ_NETWORK_DISABLED'):
                connect_gateway('wss://api.bot.qq.com/websocket/')
            with self.assertRaisesRegex(Exception, 'M2_PROVIDER_NETWORK_DISABLED'):
                TrialQwenAdapter(Mock())._trial_client(None, 1)

    def test_fake_candidate_is_management_specific_and_exact(self):
        scope = prepared_scope(ConversationOptions(trigger_mode='mention_ai', memory_enabled=True))
        resource = ROOT/'apps/ai_service/resources/management_qq_hybrid_candidate.json'
        record = json.loads(resource.read_text(encoding='utf-8'))
        self.assertEqual(record, candidate_record(scope))
        self.assertEqual(record['contract'], CONTRACT)
        self.assertEqual(scope['deployment'], 'fishery-management')
        self.assertIsNone(record['qualification_id'])
        self.assertFalse(record['can_execute_real'])
        self.assertFalse(record['can_deliver_real'])
        # Explicitly bind the M1 RO implementation and Management domain source;
        # no implicit reliance on a matching file layout in another repository.
        import hashlib
        for name in ('repository', 'schema', 'service', 'analysis', 'rules', 'diagnosis'):
            path = 'apps/monitoring/'+name+'.py'
            self.assertEqual(scope['implementation'][path], hashlib.sha256((ROOT/path).read_bytes()).hexdigest())

    def test_sdk_fake_factory_rejects_non_memory_transport_before_io(self):
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key='fictional', max_retries=0,
                             http_client=httpx.AsyncClient(trust_env=False))
        owner = memory_sdk_factory(lambda *_: client)(Mock(), 1)
        try:
            with self.assertRaisesRegex(Exception, 'SESSION_RUN_MEMORY_HTTP_REQUIRED'):
                _ = owner.chat
        finally:
            import asyncio
            asyncio.run(owner.close())

    def test_web_still_requires_knowledge_and_m2_has_only_current_capability(self):
        with self.assertRaisesRegex(ValueError, 'KNOWLEDGE_SERVICE_REQUIRED'):
            ManagementAssistantService(Mock(), credentials=None, traces=None, policy_directory=ROOT)
        for capability in ('history', 'events', 'knowledge', 'ack', 'delete'):
            with self.subTest(capability=capability), self.assertRaises(BotError):
                GroupAccess('group', 'device', ('member',), (capability,))

    def test_official_gateway_policy_stays_exact_despite_disabled_network(self):
        for host in ('api.bot.qq.com', 'api.sgroup.qq.com'):
            self.assertEqual(gateway_url('wss://'+host+'/websocket/'), 'wss://'+host+'/websocket/')
        for url in ('ws://api.bot.qq.com/websocket/', 'wss://api.bot.qq.com.evil/websocket/',
                    'wss://evil.api.bot.qq.com/websocket/', 'wss://api.bot.qq.com/websocket/?token=fictional',
                    'wss://api.bot.qq.com:4430/websocket/', 'wss://user@api.bot.qq.com/websocket/'):
            with self.subTest(url=url), self.assertRaises(BotError):
                gateway_url(url)

    def test_cli_imports_independently_and_has_no_run_flag(self):
        result = subprocess.run([sys.executable, '-I', '-B', '-c',
            "import sys;sys.path.insert(0,sys.argv[1]);from apps.qq_bot.__main__ import main;main(['--check']);"
            "assert not any(n.startswith('fishery_ai') for n in sys.modules)", str(ROOT)],
            capture_output=True, text=True, timeout=12, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['code'], 'M2_QQ_BOT_DISABLED')


class SourceBoundaryTests(unittest.TestCase):
    setUp = fixtures.QQFixture.setUp
    make = fixtures.QQFixture.make
    ingest = fixtures.QQFixture.ingest

    def test_no_writes_or_schema_change_and_cross_device_is_denied(self):
        before = self.path.read_bytes()
        source = InstanceMonitoring(MonitoringSourceConfig('m2', self.instance, ('sim-pond-1',)))
        source.capture_water('sim-pond-1')
        self.assertEqual(source._service.repository.read_only, True)
        with source._service.repository.connection() as db:
            self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 1)
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute('DELETE FROM events')
        with self.assertRaisesRegex(BotError, 'MONITORING_DEVICE_NOT_APPROVED'):
            source.capture_water('sim-pond-2')
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_corrupt_v1_rejected_without_repair(self):
        for case in ('missing', 'corrupt', 'v1'):
            with self.subTest(case=case):
                root = self.root/case
                root.mkdir()
                db = root/'monitoring.sqlite3'
                if case == 'corrupt':
                    db.write_bytes(b'fictional invalid sqlite')
                if case == 'v1':
                    connection = sqlite3.connect(db)
                    connection.execute('PRAGMA user_version=1')
                    connection.execute('CREATE TABLE existing_data (id INTEGER)')
                    connection.commit(); connection.close()
                before = db.read_bytes() if db.exists() else None
                with self.assertRaises(BotError):
                    InstanceMonitoring(MonitoringSourceConfig('m2', root, ('sim-pond-1',)))
                self.assertEqual(before, db.read_bytes() if db.exists() else None)
