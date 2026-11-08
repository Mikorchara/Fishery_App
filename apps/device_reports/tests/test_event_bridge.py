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

    def send(self,*,report_id='sample-1',at=None,**fields):
        report=fixture.report();at=at or self.now
        report.update(fields,report_id=report_id,sent_at=at.isoformat())
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

    def test_new_report_events_from_receiver_and_gap_without_pending_packets(self):
        # The behavior result is a file snapshot carried on multiple reports.
        behavior=dict(report_id='behavior-file-synthetic',source='slowfast-json',
            aggregation_policy='independent_video_results',result_semantics='snapshot_not_additive',
            new_result=True,result_timestamp=self.now.isoformat(),status='abnormal',is_abnormal=True,
            results=[dict(video='synthetic.mp4',label='异常',is_abnormal=True)],
            report_context=dict(aggregation_policy='peak_frame_v1',abnormality_status='observed',
                abnormality_count_semantics='detections_in_one_peak_frame',observed_detection_frames=20,
                observed_abnormality_frames=10,
                detection_timestamp_ms=int(self.now.timestamp()*1000)))

        def events():
            return {event['code']:event for event in self.service.events(device_id=fixture.DEVICE)}

        for index in range(3):
            if index:
                self.now+=timedelta(minutes=1)
                behavior.update(new_result=False)
                behavior['report_context']['detection_timestamp_ms']=int(self.now.timestamp()*1000)
            self.assertEqual(self.send(report_id=f'peak-{index}',behavior=behavior).json['status'],'accepted')
            self.assertEqual(self.bridge.sync_once(),1)
        self.assertEqual(set(events()),{'DEVICE_REPORT_APPEARANCE','DEVICE_REPORT_BEHAVIOR'})
        self.assertEqual(events()['DEVICE_REPORT_APPEARANCE']['last_batch_id'],'peak-2')

        self.now+=timedelta(minutes=3)
        self.assertEqual(self.bridge.sync_once(),0)
        gap=events()['DEVICE_REPORT_GAP']
        self.assertEqual(gap['lifecycle_state'],'ACTIVE')
        self.assertEqual(self.bridge.sync_once(),0)
        self.assertEqual(events()['DEVICE_REPORT_GAP']['id'],gap['id'])

        # An older cache arrival cannot clear the active interruption.
        self.assertEqual(self.send(report_id='cache',at=self.now-timedelta(minutes=5),behavior=behavior).status_code,200)
        self.bridge.sync_once()
        self.assertEqual(events()['DEVICE_REPORT_GAP']['lifecycle_state'],'ACTIVE')
        behavior['report_context'].update(abnormality_status='not_observed',
            detection_timestamp_ms=int(self.now.timestamp()*1000))
        self.assertEqual(self.send(report_id='peak-return',behavior=behavior,abnormalities=[],
            has_abnormality=True).status_code,200)
        self.bridge.sync_once()
        after=events()
        self.assertEqual(after['DEVICE_REPORT_GAP']['id'],gap['id'])
        self.assertEqual(after['DEVICE_REPORT_GAP']['lifecycle_state'],'RESOLVED')
        self.assertEqual(after['DEVICE_REPORT_APPEARANCE']['last_batch_id'],'peak-2')
        self.assertEqual(after['DEVICE_REPORT_APPEARANCE']['lifecycle_state'],'INDETERMINATE')
