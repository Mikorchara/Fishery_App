"""Curated seed uses a new instance and keeps the existing data contract."""
from contextlib import redirect_stdout
from io import StringIO
from importlib.resources import files
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps import management_setup
from apps.knowledge.initial import (
    CURATED_KNOWLEDGE_METADATA, CURATED_KNOWLEDGE_SEED, CURATED_KNOWLEDGE_VERSION,
    INITIAL_RESOURCES, initialize_curated_knowledge,
)
from apps.knowledge.repository import KnowledgeError, KnowledgeRepository
from apps.management_paths import ManagementPaths
from apps.management_web.instance import InstanceError, initialize_instance, validate_instance


class CuratedInitialKnowledgeTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_only_curated_cards_and_exact_provenance_are_published(self):
        paths = ManagementPaths.resolve(self.root, data_root=self.root / 'curated-instance')
        count = initialize_instance(paths, knowledge_seed=CURATED_KNOWLEDGE_SEED)
        validate_instance(paths)
        corpus = json.loads(files('apps.knowledge').joinpath(
            INITIAL_RESOURCES[CURATED_KNOWLEDGE_SEED]
        ).read_text(encoding='utf-8'))
        _, records, metadata = KnowledgeRepository(paths.knowledge, read_only=True).snapshot()
        self.assertEqual(metadata['initial_knowledge_version'], CURATED_KNOWLEDGE_VERSION)
        self.assertEqual(json.loads(metadata[CURATED_KNOWLEDGE_METADATA]), corpus)
        self.assertEqual(count, len(corpus['records']))
        self.assertEqual([(
            row['id'], row['evidence_id'], row['title'], row['body'],
            row['source_id'], row['source_version'], row['origin'], row['status'],
        ) for row in records], [(
            card['id'], card['id'], card['title'], card['body'],
            card['source_url'], card['source_version'], 'builtin', 'ACTIVE',
        ) for card in corpus['records']])

    def test_existing_database_and_existing_instance_are_untouched(self):
        target = self.root / 'knowledge.sqlite3'
        contents = b'fictional-operator-knowledge-store'
        target.write_bytes(contents)
        paths = ManagementPaths.resolve(self.root, data_root=self.root / 'existing-instance')
        paths.data_root.mkdir()
        paths.knowledge.write_bytes(contents)
        with patch('apps.knowledge.initial.files', side_effect=AssertionError('existing resource')):
            with self.assertRaisesRegex(KnowledgeError, 'KNOWLEDGE_INITIAL_TARGET_EXISTS'):
                initialize_curated_knowledge(target)
            with self.assertRaisesRegex(InstanceError, 'INSTANCE_ALREADY_EXISTS'):
                initialize_instance(paths, knowledge_seed=CURATED_KNOWLEDGE_SEED)
        self.assertEqual(target.read_bytes(), contents)
        self.assertEqual(paths.knowledge.read_bytes(), contents)
        self.assertEqual(list(paths.data_root.iterdir()), [paths.knowledge])

    def test_invalid_bundled_card_leaves_no_instance(self):
        package = self.root / 'package'
        invalid_resource = package / INITIAL_RESOURCES[CURATED_KNOWLEDGE_SEED]
        invalid_resource.parent.mkdir(parents=True)
        invalid_resource.write_text(
            json.dumps({'version': CURATED_KNOWLEDGE_VERSION, 'records': [{'id': 'bad'}]}),
            encoding='utf-8',
        )
        paths = ManagementPaths.resolve(self.root, data_root=self.root / 'candidate')
        with patch('apps.knowledge.initial.files', return_value=package):
            with self.assertRaisesRegex(InstanceError, 'KNOWLEDGE_CURATED_RESOURCE_INVALID'):
                initialize_instance(paths, knowledge_seed=CURATED_KNOWLEDGE_SEED)
        self.assertFalse(paths.data_root.exists())
        self.assertEqual(list(self.root.iterdir()), [package])

    def test_setup_check_and_explicit_initialization_use_no_network_or_key(self):
        destination = self.root / 'curated-instance'
        args = ['--data-root', str(destination), '--knowledge-seed', CURATED_KNOWLEDGE_SEED]
        with (
            patch('apps.management_setup.ROOT', self.root),
            patch('apps.ai_backend.credentials.CredentialStore.resolve', side_effect=AssertionError('key')),
            patch('socket.socket.connect', side_effect=AssertionError('network')),
        ):
            with patch('sqlite3.connect', side_effect=AssertionError('database')), redirect_stdout(StringIO()) as out:
                self.assertEqual(management_setup.main([*args, '--check']), 0)
            metadata = json.loads(out.getvalue())
            self.assertTrue(metadata['initial_knowledge_available'])
            self.assertFalse(metadata['database_opened'])
            self.assertFalse(destination.exists())
            with redirect_stdout(StringIO()) as out:
                self.assertEqual(management_setup.main(args), 0)
            created = json.loads(out.getvalue())
            self.assertEqual(created['code'], 'MANAGEMENT_DAILY_INSTANCE_CREATED')
            self.assertGreater(created['knowledge_records'], 0)
            self.assertEqual(created['monitoring_observations'], 0)
            self.assertEqual(created['network_requests'], 0)
            self.assertTrue((destination / 'qq-isolated-instance.json').is_file())

    def test_curated_seed_requires_explicit_location(self):
        with patch('apps.management_setup.ROOT', self.root), redirect_stdout(StringIO()) as out:
            self.assertEqual(management_setup.main(['--knowledge-seed', CURATED_KNOWLEDGE_SEED]), 1)
        self.assertEqual(json.loads(out.getvalue())['code'], 'EXPLICIT_DATA_ROOT_REQUIRED')
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
