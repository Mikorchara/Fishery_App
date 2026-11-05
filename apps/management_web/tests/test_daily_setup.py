"""First download has no outputs; setup publishes one complete, new daily store."""
from contextlib import closing, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps import management_setup as setup
from apps.knowledge.repository import KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
from apps.management_web.instance import InstanceError


class DailySetupTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(dir=setup.ROOT/'outputs/test-tmp')
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)

    def test_fresh_outputs_has_searchable_knowledge_zero_observations_and_no_credentials(self):
        self.assertFalse((self.workspace/'outputs').exists())
        with patch('apps.ai_backend.credentials.CredentialStore.resolve', side_effect=AssertionError('credentials')), \
             patch('socket.socket.connect', side_effect=AssertionError('network')):
            report = setup.initialize_daily(self.workspace)
        root = setup.daily_root(self.workspace)
        self.assertEqual(report['knowledge_records'],31)
        content = KnowledgeContentService(KnowledgeRepository(root/'knowledge.sqlite3',require_existing=True))
        self.assertEqual(content.list()['total'],31)
        self.assertTrue(content.search('溶解氧'))
        with closing(sqlite3.connect((root/'monitoring.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
            for table in ('current','history','batches','events'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        marker = json.loads((root/'qq-isolated-instance.json').read_text())
        self.assertEqual(marker['root'],str(root.resolve()))
        self.assertFalse(report['qq_configured'])
        self.assertEqual(report['network_requests'],0)

    def test_existing_instance_is_not_opened_or_overwritten(self):
        setup.initialize_daily(self.workspace)
        root = setup.daily_root(self.workspace)
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        with patch('sqlite3.connect', side_effect=AssertionError('existing database')):
            with self.assertRaisesRegex(InstanceError,'INSTANCE_ALREADY_EXISTS'):
                setup.initialize_daily(self.workspace)
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in before})

    def test_failed_seed_is_not_published(self):
        with patch('apps.management_setup.initialize_instance',side_effect=InstanceError('SEED_FAILED')):
            with self.assertRaisesRegex(InstanceError,'SEED_FAILED'):
                setup.initialize_daily(self.workspace)
        self.assertFalse(setup.daily_root(self.workspace).exists())
        self.assertEqual(list((self.workspace/'outputs').iterdir()),[])

    def test_check_does_not_open_database_or_read_private_store(self):
        with patch('apps.management_setup.ROOT',self.workspace), \
             patch('sqlite3.connect',side_effect=AssertionError('database')), \
             patch('apps.ai_backend.credentials.CredentialStore.resolve',side_effect=AssertionError('key')), \
             patch('socket.getaddrinfo',side_effect=AssertionError('network')),redirect_stdout(StringIO()) as output:
            self.assertEqual(setup.main(['--check']),0)
        value=json.loads(output.getvalue())
        self.assertFalse(value['database_opened'])
        self.assertFalse(value['credential_checked'])
        self.assertEqual(value['network_requests'],0)
