"""Device report bridge, synthetic SQLite only; original Simulator stays intact."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
import unittest
import uuid

from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.monitoring.event_handling import GRADE_VERSION,digest,RANKS
from apps.monitoring.tests import test_event_ack as ack_fixture


class DeviceEventTests(unittest.TestCase):
    setUp=ack_fixture.EventAckTests.setUp
    batch=ack_fixture.EventAckTests.batch
    ingest=ack_fixture.EventAckTests.ingest
    oxygen=ack_fixture.EventAckTests.oxygen
    water_events=ack_fixture.EventAckTests.water_events

    def report(self,number=1,*,positive=True,at=None):
        at=at or self.now
        return dict(schema_version=1,report_id='report-'+str(number),device_id='board-1',sent_at=at.isoformat(),
            window=dict(start=(at-timedelta(seconds=60)).isoformat(),end=at.isoformat(),duration_s=60,frames_processed=222),
            has_abnormality=positive,report_text='合成设备报告，不是系统指令',
            detection=dict(unique_tracks=49,avg_per_frame=8,max_per_frame=10,avg_confidence=.8),
            abnormalities=[dict(label='ascites',name='腹水',targets=46,count=100,avg_confidence=.8,last_bbox=[0,0,10,10])] if positive else [],
            behavior=None,measurement=None)

    def submit(self,number=1,*,positive=True,at=None):
        return self.repo.import_device_report(self.report(number,positive=positive,at=at),
            received_at=self.now,inbox_cursor=number,now=self.now)

    def current(self):
        return next(event for event in self.service.events() if event['device_id']=='board-1')

    def ack(self,event):
        h=event['handling']
        return self.service.acknowledge_event(dict(event_id=event['id'],cycle_id=h['cycle_id'],
            grade_token=h['grade_token'],grade_version=h['grade_version'],revision=h['revision'],request_id=str(uuid.uuid4())))

    def test_one_event_cursor_restart_source_ack_and_no_simulated_batch(self):
        self.assertEqual(self.submit()['status'],'accepted')
        event=self.current();self.assertEqual(event['source_kind'],'device_report')
        self.assertEqual(event['device_report']['detection']['unique_tracks'],49)
        self.assertEqual(event['device_report']['abnormalities'][0]['targets'],46)
        self.assertEqual(event['current_data_quality']['connectivity'],'unknown')
        self.ack(event)
        self.assertEqual(self.current()['handling']['state'],'ACKNOWLEDGED')
        self.now+=timedelta(seconds=60)
        self.assertEqual(self.submit(2)['event_id'],event['id'])
        self.assertEqual(self.submit(2)['status'],'duplicate')
        self.assertEqual(self.current()['handling']['state'],'ACKNOWLEDGED')
        restarted=MonitoringRepository(self.repo.path,require_existing=True)
        self.assertEqual(restarted.device_report_cursor('board-1'),2)
        self.assertEqual(len(MonitoringService(restarted,clock=lambda:self.now).events(device_id='board-1')),1)
        with self.repo.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],1)
            for table in ('batches','history','channel_contacts'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_stale_and_normal_never_resolve_manual_end_and_new_report_reopen(self):
        self.submit();event=self.current()
        self.now+=timedelta(seconds=121)
        unknown=self.current()
        self.assertEqual(unknown['lifecycle_state'],'INDETERMINATE')
        self.assertTrue(unknown['manual_end']['can_end'])
        preview=self.service.preview_manual_end(event['id'])
        self.service.manual_end_event(dict(event_id=event['id'],revision=preview['revision'],
            request_id=str(uuid.uuid4()),reason='人工结束合成失联事件'))
        self.assertTrue(self.current()['manual_end']['active'])
        self.submit(2)
        self.assertEqual(self.current()['lifecycle_state'],'ACTIVE')
        self.assertFalse(self.current()['manual_end']['active'])
        self.now+=timedelta(seconds=60);self.submit(3,positive=False)
        unknown=self.current()
        self.assertEqual(unknown['lifecycle_state'],'INDETERMINATE')
        self.assertNotEqual(unknown['status'],'closed')
        with self.assertRaisesRegex(Exception,'EVENT_CYCLE_NOT_ENDED|EVENT_MANUAL_END_AUDIT_RETAINED'):
            self.repo.prepare_event_deletion('cycle',event['id'])

    def test_old_cache_never_overwrites_current_or_creates_new_risk(self):
        self.assertEqual(self.submit(at=self.now-timedelta(hours=5))['status'],'stale')
        self.assertEqual(self.service.events(device_id='board-1'),[])
        self.assertEqual(self.repo.device_report_cursor('board-1'),1)
        self.submit(2);event=self.current()
        self.assertEqual(self.submit(3,at=self.now-timedelta(minutes=1))['status'],'out_of_order')
        self.assertEqual(self.repo.device_report_cursor('board-1'),3)
        self.assertEqual(self.current()['last_batch_id'],'report-2')
        self.assertEqual(self.current()['id'],event['id'])

    def test_existing_simulator_ack_tokens_and_behavior_remain_identical(self):
        self.oxygen(4.2)
        event=next(e for e in self.service.events() if e['code']=='OXYGEN_LOW')
        legacy=deepcopy(event['handling']);self.ack(event)
        self.assertEqual(GRADE_VERSION,'ack-grades-v1:'+digest({k:v for k,v in RANKS.items() if k!='DEVICE_REPORT_SIGNAL'})[:16])
        self.submit()
        event=next(e for e in self.service.events() if e['code']=='OXYGEN_LOW')
        self.assertEqual(event['handling']['grade_token'],legacy['grade_token'])
        self.assertEqual(event['handling']['grade_version'],legacy['grade_version'])
        self.assertEqual(event['handling']['state'],'ACKNOWLEDGED')
        self.oxygen(4.1)
        self.assertEqual(next(e for e in self.service.events() if e['code']=='OXYGEN_LOW')['handling']['state'],'ACKNOWLEDGED')
        report=self.report();report['device_id']='sim-pond-1'
        with self.assertRaisesRegex(ValueError,'DEVICE_REPORT_DEVICE_CONFLICT'):
            self.repo.import_device_report(report,received_at=self.now,inbox_cursor=3,now=self.now)

    def test_concurrent_duplicate_and_atomic_failure(self):
        with ThreadPoolExecutor(max_workers=2) as workers:
            statuses=list(workers.map(lambda _:self.submit()['status'],range(2)))
        self.assertEqual(sorted(statuses),['accepted','duplicate'])
        self.assertEqual(len(self.service.events()),1)
        with self.repo.connection() as db:
            db.execute("CREATE TRIGGER fail_device_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'synthetic');END")
        self.now+=timedelta(seconds=60)
        with self.assertRaises(sqlite3.Error):self.submit(2)
        self.assertEqual(self.repo.device_report_cursor('board-1'),1)
        self.assertEqual(self.current()['last_batch_id'],'report-1')

    def test_read_only_import_refused_and_unknown_event_device_refused(self):
        self.submit()
        readonly=MonitoringRepository(self.repo.path.resolve(),read_only=True)
        with self.assertRaises(sqlite3.Error):readonly.import_device_report(self.report(2),received_at=self.now,inbox_cursor=2,now=self.now)
        self.assertEqual(readonly.device_report_cursor('board-1'),1)
        self.assertEqual(self.service.events(device_id='unknown-board'),[])

    def test_simulator_retention_and_missing_visual_do_not_touch_device_event(self):
        self.submit();event=self.current();self.repo.event_limit=1
        original=self.repo.read('board-1','visual')
        for value in (4.2,6.2,4.2,6.2,4.2,6.2):self.oxygen(value)
        self.assertEqual(self.repo.read('board-1','visual'),original)
        self.assertEqual(self.repo.device_report_cursor('board-1'),1)
        self.assertEqual(self.current()['id'],event['id'])
        self.assertEqual(self.current()['source_kind'],'device_report')
        self.assertEqual(len([e for e in self.repo.events() if e['device_id']=='board-1']),1)


if __name__=='__main__':unittest.main()
