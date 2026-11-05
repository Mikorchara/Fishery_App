"""Real receiver + local bridge + existing event HTTP; synthetic SQLite only."""
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from apps.device_reports.tests import test_reports as fixture
from apps.device_reports.__main__ import create_receiver
from apps.device_reports.storage import ReportStore
from apps.device_reports.bridge import DeviceEventBridge
from apps.management_web.app import create_app
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator


class DeviceBridgeTests(unittest.TestCase):
    def setUp(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.now=fixture.NOW
        self.store=ReportStore.initialize(self.root/'reports')
        self.repo=MonitoringRepository(self.root/'monitoring.sqlite3')
        self.service=MonitoringService(self.repo,clock=lambda:self.now)
        sim=Simulator(start=self.now-timedelta(seconds=30))
        for _ in range(3):self.service.ingest(sim.advance())
        self.receiver=create_receiver(self.store,device_id=fixture.DEVICE,token=fixture.TOKEN,
                                      clock=lambda:self.now).test_client()
        self.bridge=DeviceEventBridge(ReportStore(self.root/'reports',read_only=True),self.repo,
            fixture.DEVICE,clock=lambda:self.now,interval=.01)
        self.addCleanup(self.bridge.close)

    def send(self,*,report_id='sample-1',at=None):
        report=fixture.report();at=at or self.now
        report.update(report_id=report_id,sent_at=at.isoformat())
        report['window'].update(start=(at-timedelta(seconds=39)).isoformat(),end=at.isoformat())
        return self.receiver.post('/api/fish/reports',data=json.dumps(report),content_type='application/json',
                                  headers={'X-Device-Token':fixture.TOKEN})

    def test_receive_event_page_duplicate_restart_and_original_water_unchanged(self):
        before=self.service.capture_water('sim-pond-1').to_dict() if hasattr(self.service.capture_water('sim-pond-1'),'to_dict') else self.repo.read('sim-pond-1','water')
        self.assertEqual(self.send().json['status'],'accepted')
        self.assertEqual(self.bridge.sync_once(),1)
        app=create_app(data_service=self.service,simulation_mode='water-only',
            device_report_store=ReportStore(self.root/'reports',read_only=True),device_report_device_id=fixture.DEVICE,
            device_event_bridge=self.bridge)
        response=app.test_client().get('/api/bootstrap')
        self.assertEqual(response.status_code,200)
        payload=response.json
        event=next(e for e in payload['events'] if e['source_kind']=='device_report')
        self.assertEqual(event['device_report']['report_id'],'sample-1')
        self.assertTrue(event['handling']['can_ack'])
        self.assertEqual(event['lifecycle_state'],'ACTIVE')
        self.assertEqual(payload['devices'][0]['id'],'sim-pond-1')
        self.assertEqual(len(payload['devices']),1)
        self.assertTrue(payload['integration']['device_events']['enabled'])
        self.assertEqual(self.send().json['status'],'duplicate')
        self.assertEqual(self.bridge.sync_once(),0)
        restarted=DeviceEventBridge(self.bridge.store,MonitoringRepository(self.repo.path,require_existing=True),fixture.DEVICE)
        self.assertEqual(restarted.sync_once(),0)
        self.assertEqual(len(self.service.events(device_id=fixture.DEVICE)),1)
        after=self.service.capture_water('sim-pond-1').to_dict() if hasattr(self.service.capture_water('sim-pond-1'),'to_dict') else self.repo.read('sim-pond-1','water')
        self.assertEqual(before,after)

    def test_old_report_kept_in_inbox_without_live_event(self):
        self.assertEqual(self.send(at=self.now-timedelta(hours=5)).status_code,200)
        self.bridge.sync_once()
        self.assertEqual(self.service.events(device_id=fixture.DEVICE),[])
        self.assertEqual(self.store.recent(fixture.DEVICE,now=self.now)['items'][0]['freshness'],'stale')

    def test_local_import_failure_keeps_pending_report_for_next_sync(self):
        self.send()
        with patch.object(self.repo,'import_device_report',side_effect=OSError('synthetic storage failure')):
            with self.assertRaises(OSError):self.bridge.sync_once()
        self.assertEqual(self.repo.device_report_cursor(fixture.DEVICE),0)
        self.assertEqual(self.bridge.sync_once(),1)
        self.assertEqual(len(self.service.events(device_id=fixture.DEVICE)),1)

    def test_background_bridge_processes_and_joins_owned_worker(self):
        self.send();completed=threading.Event()
        original=self.repo.import_device_report
        def consume(*args,**kwargs):
            result=original(*args,**kwargs);completed.set();return result
        with patch.object(self.repo,'import_device_report',side_effect=consume):
            self.bridge.start();self.assertTrue(completed.wait(5));self.bridge.close()
        self.assertFalse(self.bridge._thread.is_alive())
        self.assertEqual(self.repo.device_report_cursor(fixture.DEVICE),1)
