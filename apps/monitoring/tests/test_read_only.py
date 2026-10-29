"""Only new synthetic stores: DB permissions, snapshots, bounds and RW compatibility."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest

from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator


class ReadOnlyRepositoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root/'monitoring.sqlite3'
        self.writer = MonitoringRepository(self.path)
        self.now = datetime(2026,10,25,tzinfo=timezone.utc)
        self.sim = Simulator(start=self.now, session_id='read-only-test')
        self.service = MonitoringService(self.writer, clock=lambda:self.now)
        self.ingest()

    def ingest(self):
        batch = self.sim.advance()
        self.now = datetime.fromisoformat(batch['timestamp'])
        batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2,min=2.2,max=2.2,latest=2.2)
        self.service.ingest(batch)

    def fingerprint(self):
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_ro_query_only_and_all_mutations_rejected_without_change(self):
        before = self.fingerprint()
        reader = MonitoringRepository(self.path, read_only=True)
        statements = ["DELETE FROM events", "UPDATE current SET received_at='bad'",
                      'CREATE TABLE forbidden(id)', 'PRAGMA user_version=99',
                      'PRAGMA query_only=OFF', "ATTACH DATABASE ':memory:' AS other",
                      'PRAGMA journal_mode=WAL', 'VACUUM']
        for sql in statements:
            with self.subTest(sql=sql), reader.connection() as db:
                self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0],1)
                with self.assertRaises(sqlite3.Error):
                    db.execute(sql)
        self.assertEqual(before,self.fingerprint())
        with reader.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)

    def test_missing_and_empty_never_create_or_initialize(self):
        missing = self.root/'absent-parent'/'missing.sqlite3'
        with self.assertRaises(sqlite3.Error):
            MonitoringRepository(missing,read_only=True)
        self.assertFalse(missing.parent.exists())
        empty = self.root/'empty.sqlite3'; empty.touch()
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_MONITORING_STORAGE_SCHEMA'):
            MonitoringRepository(empty,read_only=True)
        self.assertEqual(empty.stat().st_size,0)

    def test_v1_never_auto_migrates(self):
        old = self.root/'v1.sqlite3'
        with closing(sqlite3.connect(old)) as db:
            db.execute('PRAGMA user_version=1')
        before = old.read_bytes()
        with self.assertRaisesRegex(ValueError,'MONITORING_SCHEMA_UPGRADE_REQUIRED'):
            MonitoringRepository(old,read_only=True)
        self.assertEqual(before,old.read_bytes())

    def test_default_writer_still_ingests_and_reader_sees_new_commits(self):
        reader = MonitoringRepository(self.path,read_only=True)
        first = reader.read('sim-pond-1','water')['batch_id']
        self.ingest()
        self.assertNotEqual(first,reader.read('sim-pond-1','water')['batch_id'])
        self.assertFalse(self.writer.read_only)

    def test_sql_time_work_budget_and_connection_cleanup(self):
        reader = MonitoringRepository(self.path,read_only=True)
        started=time.monotonic()
        with reader.connection() as db, self.assertRaises(sqlite3.OperationalError):
            db.execute('''WITH RECURSIVE x(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM x)
                          SELECT sum(n) FROM x''').fetchone()
        self.assertLess(time.monotonic()-started,3)
        # No failed read connection/transaction holds a lock over the writer.
        self.ingest()
        self.assertIsNotNone(reader.read('sim-pond-1','water'))

    def test_wal_concurrent_reader_and_writer_do_not_use_immutable_snapshot(self):
        with self.writer.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
        reader = MonitoringRepository(self.path,read_only=True)
        with reader.connection() as db:
            db.execute('BEGIN')
            count=db.execute('SELECT count(*) FROM batches').fetchone()[0]
            self.ingest()
            self.assertEqual(count,db.execute('SELECT count(*) FROM batches').fetchone()[0])
        with reader.connection() as db:
            self.assertEqual(count+1,db.execute('SELECT count(*) FROM batches').fetchone()[0])
        with ThreadPoolExecutor(max_workers=4) as workers:
            values=list(workers.map(lambda _: reader.read('sim-pond-1','water')['batch_id'],range(16)))
        self.assertEqual(len(set(values)),1)

    def test_exclusive_lock_fails_in_bounded_time_then_recovers(self):
        reader = MonitoringRepository(self.path,read_only=True)
        with closing(sqlite3.connect(self.path)) as locked:
            locked.execute('BEGIN EXCLUSIVE')
            started=time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):
                reader.read('sim-pond-1','water')
            self.assertLess(time.monotonic()-started,1.5)
            locked.rollback()
        self.assertIsNotNone(reader.read('sim-pond-1','water'))

    def test_explicit_absolute_path_bool_and_corrupt_database_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'READ_ONLY_PATH_MUST_BE_ABSOLUTE'):
            MonitoringRepository('not-an-instance.sqlite3',read_only=True)
        with self.assertRaisesRegex(ValueError,'INVALID_READ_ONLY_OPTION'):
            MonitoringRepository(self.path,read_only='false')
        bad=self.root/'corrupt.sqlite3';bad.write_bytes(b'not a SQLite database')
        before=bad.read_bytes()
        with self.assertRaises(sqlite3.Error):MonitoringRepository(bad,read_only=True)
        self.assertEqual(before,bad.read_bytes())

    def test_length_and_wall_clock_budgets_fail_without_holding_writer_lock(self):
        from unittest.mock import patch
        reader=MonitoringRepository(self.path,read_only=True)
        with reader.connection() as db,self.assertRaises(sqlite3.Error):
            db.execute('SELECT zeroblob(262145)').fetchone()
        with patch('apps.monitoring.repository.monotonic',side_effect=[0,3]), \
                reader.connection() as db,self.assertRaisesRegex(sqlite3.OperationalError,'interrupted'):
            db.execute('WITH RECURSIVE x(n) AS (VALUES(1) UNION ALL SELECT n+1 FROM x WHERE n<10000) SELECT sum(n) FROM x').fetchone()
        self.ingest()

    def test_rollback_journal_reader_writer_concurrency_and_service_writes_rejected(self):
        reader=MonitoringRepository(self.path,read_only=True)
        def reads():
            return [reader.read('sim-pond-1','water')['batch_id'] for _ in range(12)]
        with ThreadPoolExecutor(max_workers=3) as workers:
            futures=[workers.submit(reads) for _ in range(2)]
            writer=workers.submit(lambda:[self.ingest() for _ in range(6)])
            writer.result(timeout=15)
            self.assertTrue(all(f.result(timeout=15) for f in futures))
        before=self.fingerprint()
        batch=self.sim.advance()
        readonly_service=MonitoringService(reader,clock=lambda:datetime.fromisoformat(batch['timestamp']))
        with self.assertRaises(sqlite3.Error):readonly_service.ingest(batch)
        self.assertEqual(before,self.fingerprint())



if __name__ == "__main__":unittest.main()
