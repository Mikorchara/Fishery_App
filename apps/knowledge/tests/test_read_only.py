"""Synthetic read-only Knowledge access; no user store or credentials."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.knowledge.repository import KnowledgeError, KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
from apps.knowledge.tests.support import seed

ROOT = Path(__file__).resolve().parents[3]
VALUE = dict(title='紫珊瑚', category='环境管理', body='紫珊瑚是本次隔离测试使用的背景知识标记。')


class ReadOnlyKnowledgeTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'outputs/test-tmp'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'knowledge #1.sqlite3'
        seed(self.path)
        self.writer = KnowledgeContentService(KnowledgeRepository(self.path, require_existing=True))
        self.item = self.writer.create(VALUE)

    def digest(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_all_connections_are_ro_query_only_and_shared_search_is_unchanged(self):
        before = self.digest()
        original = sqlite3.connect
        opened = []
        def read_only(database, *args, **kwargs):
            self.assertIn('?mode=ro', str(database))
            self.assertTrue(kwargs.get('uri'))
            opened.append(database)
            return original(database, *args, **kwargs)
        with patch('apps.knowledge.repository.sqlite3.connect', side_effect=read_only):
            repository = KnowledgeRepository(self.path, read_only=True)
            self.assertTrue(repository.require_existing)
            with repository.connection() as connection:
                self.assertEqual(connection.execute('PRAGMA query_only').fetchone()[0], 1)
            reader = KnowledgeContentService(repository)
            hits = reader.search('紫珊瑚')
            self.assertTrue(any(hit.evidence_id == self.item['id'] for hit in hits))
            self.assertEqual(reader.get(self.item['id']), self.item)
        self.assertGreaterEqual(len(opened), 4)
        self.assertEqual(before, self.digest())

    def test_write_api_rejected_before_connect_and_engine_also_refuses_writes(self):
        reader = KnowledgeContentService(KnowledgeRepository(self.path, read_only=True))
        before = self.digest()
        with patch('apps.knowledge.repository.sqlite3.connect', side_effect=AssertionError('write must not open DB')):
            actions = (
                lambda: reader.create(VALUE),
                lambda: reader.edit(self.item['id'], {**VALUE, 'version': 1}),
                lambda: reader.set_status(self.item['id'], dict(version=1, status='DELETED')),
            )
            for action in actions:
                with self.assertRaisesRegex(KnowledgeError, '^KNOWLEDGE_READ_ONLY$'):
                    action()
            with self.assertRaisesRegex(KnowledgeError, '^KNOWLEDGE_READ_ONLY$'):
                with reader.repository.connection(write=True):
                    self.fail('write connection granted')
        for sql in ('DELETE FROM knowledge_records', 'CREATE TABLE forbidden(id)', 'PRAGMA user_version=99'):
            with self.subTest(sql=sql), self.assertRaises(KnowledgeError):
                with reader.repository.connection() as connection:
                    connection.execute(sql)
        # Even disabling query_only does not override SQLite's mode=ro.
        with self.assertRaises(KnowledgeError):
            with reader.repository.connection() as connection:
                connection.execute('PRAGMA query_only=OFF')
                connection.execute('DELETE FROM knowledge_records')
        self.assertEqual(before, self.digest())

    def test_missing_empty_old_or_corrupt_database_never_initializes_or_repairs(self):
        missing = self.root / 'missing-parent' / 'knowledge.sqlite3'
        with self.assertRaises(KnowledgeError):
            KnowledgeRepository(missing, read_only=True)
        self.assertFalse(missing.parent.exists())
        for name, body in (('empty.sqlite3', b''), ('corrupt.sqlite3', b'not sqlite')):
            path = self.root / name
            path.write_bytes(body)
            with self.assertRaises(KnowledgeError):
                KnowledgeRepository(path, read_only=True)
            self.assertEqual(path.read_bytes(), body)
        old = self.root / 'old.sqlite3'
        with closing(sqlite3.connect(old)) as connection:
            connection.execute('CREATE TABLE old_records(body TEXT)')
            connection.execute('PRAGMA user_version=1')
        before = old.read_bytes()
        with self.assertRaisesRegex(KnowledgeError, 'MIGRATION_REQUIRED'):
            KnowledgeRepository(old, read_only=True)
        self.assertEqual(before, old.read_bytes())

    def test_existing_reader_sees_committed_edits_but_rejects_replaced_database(self):
        reader = KnowledgeContentService(KnowledgeRepository(self.path, read_only=True))
        self.assertTrue(any(hit.evidence_id == self.item['id'] for hit in reader.search('紫珊瑚')))
        self.writer.edit(self.item['id'], dict(title='银珊瑚', category='环境管理', body='银珊瑚是更新后的隔离知识。', version=1))
        hits = reader.search('银珊瑚')
        self.assertTrue(any(hit.evidence_id == self.item['id'] and hit.source_version == '2' for hit in hits))
        replacement = self.root / 'replacement.sqlite3'
        replacement.write_bytes(self.path.read_bytes())
        os.replace(replacement, self.path)
        with self.assertRaisesRegex(KnowledgeError, '^KNOWLEDGE_DATABASE_REPLACED$'):
            reader.search('银珊瑚')

    def test_read_only_and_original_writer_can_share_one_database(self):
        reader = KnowledgeContentService(KnowledgeRepository(self.path, read_only=True))
        def read_many():
            for _ in range(8):
                self.assertTrue(reader.list()['total'] >= 1)
        def write_many():
            for index in range(8):
                self.writer.create({**VALUE, 'title': f'紫珊瑚{index}'})
        with ThreadPoolExecutor(2) as pool:
            futures = (pool.submit(read_many), pool.submit(write_many))
            for future in futures:
                future.result(timeout=12)
        self.assertEqual(reader.list()['total'], self.writer.list()['total'])
        with self.assertRaises(KnowledgeError):
            KnowledgeRepository(self.path, read_only='yes')


if __name__ == '__main__':
    unittest.main()
