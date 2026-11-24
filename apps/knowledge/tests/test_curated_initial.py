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
    COMBINED_KNOWLEDGE_SEED, COMBINED_KNOWLEDGE_VERSION, CURATED_KNOWLEDGE_METADATA,
    CURATED_KNOWLEDGE_SEED, CURATED_KNOWLEDGE_VERSION, INITIAL_RESOURCES,
    initialize_curated_knowledge, initialize_initial_knowledge,
)
from apps.knowledge.repository import KnowledgeError, KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
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

    def test_combined_new_instance_preserves_background_and_scoped_evidence(self):
        background = self.root / 'legacy-fixture.sqlite3'
        initialize_initial_knowledge(background)
        _, expected_background, expected_metadata = KnowledgeRepository(background, read_only=True).snapshot()
        paths = ManagementPaths.resolve(self.root, data_root=self.root / 'combined-instance')
        count = initialize_instance(paths, knowledge_seed=COMBINED_KNOWLEDGE_SEED)
        validate_instance(paths)
        repo = KnowledgeRepository(paths.knowledge, require_existing=True)
        _, rows, metadata = repo.snapshot()
        self.assertEqual(count, 43)
        self.assertEqual(rows[:31], expected_background)
        self.assertEqual({key: metadata[key] for key in expected_metadata}, expected_metadata)
        self.assertEqual(metadata['initial_knowledge_version'], COMBINED_KNOWLEDGE_VERSION)
        self.assertEqual(json.loads(metadata[CURATED_KNOWLEDGE_METADATA])['version'], CURATED_KNOWLEDGE_VERSION)

        service = KnowledgeContentService(repo)
        related = '日本鳗鲡在 7.26 mg/L 溶解氧时，摄食率是多少？'
        hits, scoped = service.search_with_scope(related, question=related)
        self.assertTrue(scoped)
        self.assertTrue(any('12.4%' in evidence.text for evidence in hits))
        unsupported = '日本鳗鲡在 9-10 mg/L 溶解氧时，摄食率是多少？'
        self.assertEqual(service.search_with_scope(unsupported, question=unsupported), ((), True))
        background_hits, scoped = service.search_with_scope('鳗鲡适宜养殖水温')
        self.assertFalse(scoped)
        self.assertTrue(any(evidence.source_id == 'legacy:eel_knowledge.json' for evidence in background_hits))

        created = service.create(dict(title='紫色标记对照', category='自定义', body='虚构资料仅用于验收。'))
        edited = service.edit(created['id'], dict(version=created['version'], title='紫色标记复核',
            category='自定义', body='试验记录已修改。'))
        with self.assertRaisesRegex(InstanceError, 'INSTANCE_ALREADY_EXISTS'):
            initialize_instance(paths, knowledge_seed=COMBINED_KNOWLEDGE_SEED)
        self.assertEqual(service.get(created['id']), edited)
        self.assertEqual(len(repo.snapshot()[1]), 44)

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
        with (
            patch('apps.management_setup.ROOT', self.root),
            patch('apps.ai_backend.credentials.CredentialStore.resolve', side_effect=AssertionError('key')),
            patch('socket.socket.connect', side_effect=AssertionError('network')),
        ):
            for seed, count in ((CURATED_KNOWLEDGE_SEED, 12), (COMBINED_KNOWLEDGE_SEED, 43)):
                with self.subTest(seed=seed):
                    destination = self.root / seed
                    args = ['--data-root', str(destination), '--knowledge-seed', seed]
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
                    self.assertEqual(created['knowledge_records'], count)
                    self.assertEqual(created['monitoring_observations'], 0)
                    self.assertEqual(created['network_requests'], 0)
                    self.assertTrue((destination / 'qq-isolated-instance.json').is_file())

    def test_optional_seeds_require_explicit_location(self):
        for seed in (CURATED_KNOWLEDGE_SEED, COMBINED_KNOWLEDGE_SEED):
            with self.subTest(seed=seed), patch('apps.management_setup.ROOT', self.root), redirect_stdout(StringIO()) as out:
                self.assertEqual(management_setup.main(['--knowledge-seed', seed]), 1)
                self.assertEqual(json.loads(out.getvalue())['code'], 'EXPLICIT_DATA_ROOT_REQUIRED')
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
