"""First-install references use only bundled text and new synthetic databases."""
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.knowledge.initial import initialize_initial_knowledge, RESOURCE_SHA256, INITIAL_KNOWLEDGE_VERSION
from apps.knowledge.repository import KnowledgeError, KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
from apps.management_paths import ManagementPaths
from apps.management_web.instance import initialize_instance, validate_instance, InstanceError
from apps.monitoring.repository import MonitoringRepository


class InitialKnowledgeTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_bundled_resource_creates_searchable_new_knowledge_without_user_database(self):
        target = self.root/'knowledge.sqlite3'
        result = initialize_initial_knowledge(target)
        self.assertEqual(result['builtin_count'], 31)
        self.assertEqual(result['user_count'], 0)
        self.assertFalse(result['source_database_present'])
        repository = KnowledgeRepository(target, require_existing=True)
        _, records, metadata = repository.snapshot()
        self.assertEqual(len(records), 31)
        self.assertTrue(all(record['origin'] == 'builtin' for record in records))
        self.assertEqual(metadata['migration_version'], 'unified-knowledge@2')
        self.assertTrue(KnowledgeContentService(repository).search('鳗鲡低氧表现'))
        resource = Path(__file__).resolve().parents[1]/'resources/eel_knowledge_v1.json'
        self.assertEqual(hashlib.sha256(resource.read_bytes()).hexdigest(), RESOURCE_SHA256)

    def test_existing_target_is_never_opened_or_overwritten(self):
        target = self.root/'knowledge.sqlite3'
        original = b'fictional-existing-user-data'
        target.write_bytes(original)
        with patch('apps.knowledge.initial.migrate', side_effect=AssertionError('must not open target')), \
                self.assertRaisesRegex(KnowledgeError, 'KNOWLEDGE_INITIAL_TARGET_EXISTS'):
            initialize_initial_knowledge(target)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_explicit_seeded_instance_keeps_monitoring_empty_and_default_still_empty(self):
        paths = ManagementPaths.resolve(self.root, data_root=self.root/'seeded')
        initialize_instance(paths, initial_knowledge=True)
        validate_instance(paths)
        repository = KnowledgeRepository(paths.knowledge, require_existing=True)
        _, records, metadata = repository.snapshot()
        self.assertEqual(len(records), 31)
        self.assertEqual(metadata['initial_knowledge_version'], INITIAL_KNOWLEDGE_VERSION)
        self.assertEqual(metadata['initialization_version'], 'management-instance@1')
        self.assertEqual(MonitoringRepository(paths.monitoring, require_existing=True).history('pond-a','water'), [])
        self.assertFalse(paths.settings.exists())
        original = paths.knowledge.read_bytes()
        with self.assertRaisesRegex(InstanceError, 'INSTANCE_ALREADY_EXISTS'):
            initialize_instance(paths, initial_knowledge=True)
        self.assertEqual(paths.knowledge.read_bytes(), original)
        empty = ManagementPaths.resolve(self.root, data_root=self.root/'empty')
        initialize_instance(empty)
        self.assertEqual(KnowledgeRepository(empty.knowledge, require_existing=True).snapshot()[1], [])

    def test_unavailable_resource_fails_without_publishing_an_instance(self):
        paths = ManagementPaths.resolve(self.root, data_root=self.root/'instance')
        with patch('apps.knowledge.initial.files', return_value=self.root/'missing-package'), \
                self.assertRaisesRegex(InstanceError, 'KNOWLEDGE_INITIAL_RESOURCE_UNAVAILABLE'):
            initialize_instance(paths, initial_knowledge=True)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_changed_resource_fails_without_publishing_an_instance(self):
        package = self.root/'package'
        (package/'resources').mkdir(parents=True)
        resource = package/'resources/eel_knowledge_v1.json'
        resource.write_text('{}', encoding='utf8')
        paths = ManagementPaths.resolve(self.root, data_root=self.root/'instance')
        with patch('apps.knowledge.initial.files', return_value=package), \
                self.assertRaisesRegex(InstanceError, 'KNOWLEDGE_INITIAL_RESOURCE_CHANGED'):
            initialize_instance(paths, initial_knowledge=True)
        self.assertEqual(list(self.root.iterdir()), [package])
        self.assertEqual(resource.read_text(encoding='utf8'), '{}')


if __name__ == '__main__':
    unittest.main()
