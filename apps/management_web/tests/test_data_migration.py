"""MIG-4B safety gates. All records are fictional; all files stay in ignored outputs."""
from contextlib import contextmanager, closing
import io
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from apps.management_paths import ManagementPaths
from apps.management_web.instance import initialize_instance
from apps.knowledge.repository import KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
from scripts.maintenance import migrate_management_data as migration


@unittest.skipUnless(os.name == 'nt', 'Windows sharing and no-replace rename contract')
class DataMigrationTests(unittest.TestCase):
    def setUp(self):
        parent = migration.ROOT/'outputs/test-tmp'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = TemporaryDirectory(prefix='mig4b-fictional-', dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = ManagementPaths.resolve(migration.ROOT, data_root=self.root/'fixture-source')
        self.target = ManagementPaths.resolve(migration.ROOT, data_root=self.root/'FisheryManagement')
        initialize_instance(self.source)
        KnowledgeContentService(KnowledgeRepository(self.source.knowledge, require_existing=True)).create(
            {'title': 'Fictional fixture', 'category': 'water_quality', 'body': 'Synthetic test content only.'})
        self.source.settings.write_bytes(migration.encode({'schema_version': 2,
            'preferences': {'preset_id': 'dashscope-qwen38-flash-r1', 'device_id': 'sim-pond-1',
                            'transport': 'streaming', 'show_details': False},
            'output_budgets': {'dashscope-qwen38-flash-r1:normal': 2048}, 'budget_revision': 5}))
        (self.source.policy_directory/'management_assistant_policy.json').write_bytes(migration.encode(
            {'schema_version': 1, 'generation': 11, 'selected_tools': list(migration.TOOLS)}))
        (self.source.policy_directory/'tool_policies.json').write_bytes(migration.encode({'schema_version': 1,
            'modes': {'analysis': {'selected_tools': []}, 'assistant': {'selected_tools': list(migration.TOOLS[:2])}}}))
        self.operation = '20261019T000000Z-0123456789ab'
        self.backup = self.root/('FisheryManagement.mig4b-backup-'+self.operation)
        self.stage = self.root/('FisheryManagement.mig4b-stage-'+self.operation)

    def plan(self):
        return {'schema_version': 1, 'migration_id': self.operation, 'approved_head': migration.APPROVED_HEAD,
                'script_sha256': migration.sha(Path(migration.__file__)), 'source': str(self.source.data_root),
                'target': str(self.target.data_root), 'backup': str(self.backup), 'stage': str(self.stage),
                'snapshot': migration.snapshot(self.source)}

    def execute(self, plan=None, writers=lambda: None):
        with migration.freeze_files(self.source), patch.object(migration, 'parent_check'):
            return migration.execute(plan or self.plan(), self.source, self.target, writers)

    @contextmanager
    def cli_context(self):
        git = SimpleNamespace(returncode=0, stdout=migration.ROOT.as_posix()+'\n'+migration.APPROVED_HEAD+'\n')
        baseline = {key: value['sha256'] for key, value in migration.file_facts(self.source).items()}
        original = ManagementPaths.resolve
        with patch.object(migration, 'SOURCE', self.source.data_root), \
                patch.object(migration.ManagementPaths, 'resolve', wraps=ManagementPaths.resolve) as resolver, \
                patch.object(migration, 'BASELINE', baseline), \
                patch.object(migration, 'inspect_processes', return_value=str(self.root)), \
                patch.object(migration, 'parent_check'), \
                patch.object(migration.subprocess, 'run', return_value=git), \
                patch.dict(os.environ, {'LOCALAPPDATA': str(self.root)}):
            def paths(workspace, **options):
                if workspace == self.source.data_root and not options:
                    return self.source
                return original(workspace, **options)
            resolver.side_effect = paths
            yield

    def test_source_write_and_delete_are_denied_while_read_handles_held(self):
        before = migration.file_facts(self.source)
        with migration.freeze_files(self.source):
            for path in migration.files(self.source).values():
                with self.assertRaises(OSError):
                    with path.open('r+b'):
                        pass
                with self.assertRaises(OSError):
                    path.unlink()
        self.assertEqual(before, migration.file_facts(self.source))

    def test_existing_writer_is_refused_without_source_changes(self):
        before = migration.file_facts(self.source)
        with self.source.monitoring.open('r+b'):
            with self.assertRaisesRegex(migration.MigrationError, 'FILE_BUSY'):
                with migration.freeze_files(self.source):
                    self.fail('must not acquire a snapshot over an existing writer')
        self.assertEqual(before, migration.file_facts(self.source))

    def test_complete_backup_stage_publish_preserves_all_logical_data_and_source(self):
        before = migration.file_facts(self.source)
        result = self.execute()
        self.assertEqual(result['status'], 'MIGRATED_AND_VERIFIED')
        self.assertEqual(before, migration.file_facts(self.source))
        self.assertFalse(self.stage.exists())
        self.assertTrue((self.backup/'manifest.json').is_file())
        self.assertTrue((self.backup/'verification.json').is_file())
        self.assertEqual(result['application']['knowledge_count'], 1)
        self.assertEqual(result['application']['bootstrap_http'], 200)
        self.assertEqual(result['application']['provider_requests'], 0)
        for path in migration.files(self.target).values():
            migration.secure_files.inspect_policy(path)

    def test_target_already_exists_is_never_modified(self):
        self.target.data_root.mkdir()
        sentinel = self.target.data_root/'sentinel'
        sentinel.write_bytes(b'fictional existing instance')
        with self.assertRaisesRegex(migration.MigrationError, 'TARGET_ALREADY_EXISTS'):
            self.execute()
        self.assertEqual(sentinel.read_bytes(), b'fictional existing instance')
        self.assertFalse(self.backup.exists())

    def test_publication_race_preserves_competing_instance_and_stage(self):
        def other_writer():
            self.target.data_root.mkdir()
            (self.target.data_root/'sentinel').write_bytes(b'fictional concurrent instance')
        with self.assertRaisesRegex(migration.MigrationError, 'TARGET_ALREADY_EXISTS'):
            self.execute(writers=other_writer)
        self.assertTrue(self.stage.is_dir())
        self.assertTrue((self.backup/'failure.json').is_file())
        self.assertEqual((self.target.data_root/'sentinel').read_bytes(), b'fictional concurrent instance')

    def test_windows_rename_itself_refuses_racing_empty_directory(self):
        self.stage.mkdir()
        (self.stage/'fictional').write_bytes(b'data')
        rename = os.rename
        def racing(source, target):
            target.mkdir()
            rename(source, target)
        with patch.object(migration.os, 'rename', side_effect=racing), self.assertRaises(OSError):
            migration.publish(self.stage, self.target.data_root)
        self.assertTrue(self.stage.is_dir())
        self.assertEqual(list(self.target.data_root.iterdir()), [])

    def test_stage_failure_retains_backup_and_partial_stage_no_target(self):
        populate = migration.populate
        def fail_stage(source, destination):
            if destination.data_root == self.stage:
                destination.data_root.mkdir()
                raise OSError('fictional failure')
            populate(source, destination)
        with patch.object(migration, 'populate', side_effect=fail_stage), self.assertRaises(OSError):
            self.execute()
        self.assertFalse(self.target.data_root.exists())
        self.assertTrue(self.stage.exists())
        self.assertTrue((self.backup/'failure.json').exists())

    def test_post_publication_failure_preserves_complete_target(self):
        snapshot = migration.snapshot
        def fail_final(paths):
            if paths.data_root == self.target.data_root:
                raise migration.MigrationError('FICTIONAL_POST_VERIFY_FAILURE')
            return snapshot(paths)
        with patch.object(migration, 'snapshot', side_effect=fail_final), self.assertRaisesRegex(
                migration.MigrationError, 'FICTIONAL_POST_VERIFY_FAILURE'):
            self.execute()
        self.assertTrue(all(path.is_file() for path in migration.files(self.target).values()))
        self.assertTrue((self.backup/'failure.json').is_file())

    def test_backup_does_not_require_matching_sqlite_file_hashes(self):
        expected = self.plan()['snapshot']
        actual = json.loads(json.dumps(expected))
        actual['files']['knowledge']['sha256'] = 'fictional different physical image'
        actual['semantic']['databases']['knowledge']['schema_version'] = 1
        migration.require_equal(actual, expected)
        actual['semantic']['databases']['knowledge']['tables']['knowledge_records']['rows_sha256'] = 'fictional changed body'
        with self.assertRaisesRegex(migration.MigrationError, 'LOGICAL_DATA_OR_SCHEMA_MISMATCH'):
            migration.require_equal(actual, expected)

    def test_json_byte_difference_is_refused(self):
        expected = self.plan()['snapshot']
        actual = json.loads(json.dumps(expected))
        actual['files']['settings']['sha256'] = 'fictional different formatting'
        with self.assertRaisesRegex(migration.MigrationError, 'JSON_BYTES_MISMATCH'):
            migration.require_equal(actual, expected)

    def test_wal_header_or_any_sidecar_requires_review(self):
        sidecar = Path(str(self.source.monitoring)+'-wal')
        sidecar.write_bytes(b'fictional sidecar')
        with self.assertRaisesRegex(migration.MigrationError, 'SQLITE_SIDECAR'):
            migration.cold_database(self.source.monitoring)
        sidecar.unlink()
        with closing(sqlite3.connect(self.source.monitoring)) as db:
            db.execute('PRAGMA journal_mode=WAL')
        with self.assertRaisesRegex(migration.MigrationError, 'SQLITE_NOT_COLD'):
            migration.cold_database(self.source.monitoring)

    def test_unknown_process_requires_ack_but_fishery_writer_cannot_be_ignored(self):
        def response(fishery):
            return SimpleNamespace(returncode=0, stdout=migration.encode({'localappdata': str(self.root),
                'processes': [{'pid': 99999, 'name': 'fictional.exe', 'fishery_reference': fishery}]}))
        with patch.object(migration.subprocess, 'run', return_value=response(False)):
            with self.assertRaisesRegex(migration.MigrationError, 'UNCONFIRMED_WRITER'):
                migration.inspect_processes(set())
            self.assertEqual(migration.inspect_processes({99999}), str(self.root))
        with patch.object(migration.subprocess, 'run', return_value=response(True)):
            with self.assertRaisesRegex(migration.MigrationError, 'UNCONFIRMED_WRITER'):
                migration.inspect_processes({99999})

    def test_dry_run_does_not_create_backup_stage_or_target(self):
        with self.cli_context(), patch('sys.stdout', new_callable=io.StringIO) as output:
            code = migration.main(['--dry-run', '--migration-id', self.operation])
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['status'], 'DRY_RUN_READY')
        self.assertFalse(any(p.exists() for p in (self.backup, self.stage, self.target.data_root)))

    def test_permission_failure_prevents_apply_and_writes_nothing(self):
        with self.cli_context(), patch.object(migration, 'parent_check', side_effect=migration.secure_files.SecureFileError()), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            code = migration.main(['--apply', '--writers-stopped', '--migration-id', self.operation])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())['code'], 'ENV_PERMISSION_ERROR_USE_NORMAL_POWERSHELL')
        self.assertFalse(any(p.exists() for p in (self.backup, self.stage, self.target.data_root)))

    def test_cli_requires_frozen_writer_confirmation_and_accepts_exact_dry_run_plan(self):
        with self.cli_context(), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(migration.main(['--dry-run', '--migration-id', self.operation]), 0)
            plan_hash = json.loads(output.getvalue())['plan_sha256']
        with self.cli_context(), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(migration.main(['--apply', '--migration-id', self.operation,
                                            '--plan-sha256', plan_hash]), 2)
            self.assertEqual(json.loads(output.getvalue())['code'], 'WRITERS_STOPPED_CONFIRMATION_REQUIRED')
        self.assertFalse(self.target.data_root.exists())
        with self.cli_context(), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(migration.main(['--apply', '--writers-stopped', '--migration-id', self.operation,
                                            '--plan-sha256', plan_hash]), 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['status'], 'MIGRATED_AND_VERIFIED')

    def test_existing_backup_or_stage_cannot_be_reused(self):
        self.backup.mkdir()
        (self.backup/'sentinel').write_bytes(b'fictional prior attempt')
        with self.assertRaisesRegex(migration.MigrationError, 'OPERATION_PATH_ALREADY_EXISTS'):
            self.execute()
        self.assertEqual((self.backup/'sentinel').read_bytes(), b'fictional prior attempt')
        self.assertFalse(self.target.data_root.exists())

    def test_changed_mig4a_baseline_or_wrong_plan_stops_before_writes(self):
        with self.cli_context(), patch.object(migration, 'BASELINE', {}), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(migration.main(['--dry-run']), 2)
            self.assertIn('SOURCE_CHANGED_SINCE_MIG4A', json.loads(output.getvalue())['code'])
        with self.cli_context(), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(migration.main(['--apply', '--writers-stopped', '--migration-id', self.operation,
                                             '--plan-sha256', 'fictional wrong plan']), 2)
            self.assertIn('APPROVED_PLAN_MISMATCH', json.loads(output.getvalue())['code'])
        self.assertFalse(any(p.exists() for p in (self.backup, self.stage, self.target.data_root)))

    def test_verify_reads_target_only_and_writes_no_manifest_or_source(self):
        self.execute()
        before = migration.file_facts(self.target)
        audit_files = {p.name: p.read_bytes() for p in self.backup.iterdir() if p.is_file() and p.suffix == '.json'}
        snapshot = migration.snapshot
        def target_only(paths):
            self.assertEqual(paths.data_root, self.target.data_root)
            return snapshot(paths)
        with self.cli_context(), patch.object(migration, 'snapshot', side_effect=target_only), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(migration.main(['--verify', '--manifest', str(self.backup/'manifest.json')]), 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['status'], 'VERIFIED_READ_ONLY')
        self.assertEqual(before, migration.file_facts(self.target))
        self.assertEqual(audit_files, {p.name: p.read_bytes() for p in self.backup.iterdir() if p.is_file() and p.suffix == '.json'})


if __name__ == '__main__':
    unittest.main()
