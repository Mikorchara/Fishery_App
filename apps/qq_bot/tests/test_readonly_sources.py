"""New synthetic instance only: history forwarding and shared read-only RAG."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.knowledge.repository import KnowledgeError, KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
from apps.knowledge.tests.support import seed
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from apps.qq_bot.contracts import BotError
from apps.qq_bot.knowledge_source import open_readonly_knowledge
from apps.qq_bot.monitoring_source import MonitoringSourceConfig, InstanceMonitoring

ROOT = Path(__file__).resolve().parents[3]


class ReadonlySourceTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'outputs/test-tmp'
        parent.mkdir(parents=True, exist_ok=True)
        temporary = TemporaryDirectory(dir=parent)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = datetime(2026, 11, 6, tzinfo=timezone.utc)
        self.writer = MonitoringService(MonitoringRepository(self.root / 'monitoring.sqlite3'),
            device_names={'sim-pond-1': 'approved', 'sim-pond-2': 'not approved'}, clock=lambda: self.now)
        for device in ('sim-pond-1', 'sim-pond-2'):
            generator = Simulator(start=self.now-timedelta(seconds=70), device_id=device, session_id='source-'+device)
            for _ in range(6):
                self.writer.ingest(generator.advance())
        self.config = MonitoringSourceConfig('isolated-source-test', self.root, ('sim-pond-1',))
        self.source = InstanceMonitoring(self.config, clock=lambda: self.now)

    def test_history_reuses_business_service_once_and_cannot_cross_device(self):
        before = (self.root / 'monitoring.sqlite3').read_bytes()
        expected = self.writer.query_water_history('sim-pond-1', lookback_minutes=10, metrics=['ph'])
        original = self.source._service.query_water_history
        with patch.object(self.source._service, 'query_water_history', wraps=original) as query:
            result = self.source.query_water_history('sim-pond-1', lookback_minutes=10, metrics=['ph'])
            self.assertEqual(result, expected)
            self.assertEqual(query.call_count, 1)
            with self.assertRaisesRegex(BotError, 'MONITORING_DEVICE_NOT_APPROVED'):
                self.source.query_water_history('sim-pond-2', lookback_minutes=10)
            self.assertEqual(query.call_count, 1)
        self.assertEqual(before, (self.root / 'monitoring.sqlite3').read_bytes())
        default = self.source.query_water_history('sim-pond-1', lookback_minutes=30)
        self.assertEqual(set(default['metrics']), {'temperature_c', 'ph', 'dissolved_oxygen_mg_l'})

    def test_history_budget_failure_and_no_data_are_not_replaced_with_normal(self):
        with patch.object(self.source._service, 'query_water_history', side_effect=ValueError('HISTORY_QUERY_BUDGET_EXCEEDED')):
            with self.assertRaisesRegex(BotError, '^HISTORY_QUERY_BUDGET_EXCEEDED$'):
                self.source.query_water_history('sim-pond-1', lookback_minutes=10)
        with self.assertRaises(BotError):
            self.source.query_water_history('sim-pond-1', lookback_minutes=11)
        empty = self.root / 'empty'
        empty.mkdir()
        MonitoringRepository(empty / 'monitoring.sqlite3')
        reader = InstanceMonitoring(MonitoringSourceConfig('empty', empty, ('sim-pond-1',)), clock=lambda: self.now)
        self.assertEqual(reader.query_water_history('sim-pond-1', lookback_minutes=10)['status'], 'NO_DATA')

    def test_knowledge_helper_uses_only_selected_instance_and_original_search(self):
        path = self.root / 'knowledge.sqlite3'
        with self.assertRaises(KnowledgeError):
            open_readonly_knowledge(self.config)
        self.assertFalse(path.exists())
        seed(path)
        writer = KnowledgeContentService(KnowledgeRepository(path, require_existing=True))
        item = writer.create(dict(title='蓝环鳗鲡', category='环境管理', body='蓝环鳗鲡是隔离知识测试标记。'))
        before = path.read_bytes()
        reader = open_readonly_knowledge(self.config)
        self.assertIs(type(reader), KnowledgeContentService)
        self.assertTrue(reader.repository.read_only)
        self.assertEqual(reader.repository.path, path)
        self.assertTrue(any(hit.evidence_id == item['id'] for hit in reader.search('蓝环鳗鲡')))
        with self.assertRaisesRegex(KnowledgeError, 'KNOWLEDGE_READ_ONLY'):
            reader.set_status(item['id'], dict(version=1, status='DELETED'))
        self.assertEqual(before, path.read_bytes())
        with self.assertRaises(BotError):
            open_readonly_knowledge({'data_root': str(self.root)})


if __name__ == '__main__':
    unittest.main()
