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
from apps.monitoring.device_events import APPEARANCE, BEHAVIOR, DEVICE_EVENT_CODES, GAP
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
        self.assertEqual(GRADE_VERSION,'ack-grades-v1:'+digest({k:v for k,v in RANKS.items() if k not in DEVICE_EVENT_CODES})[:16])
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

    def peak_report(self, number, *, at=None, appearance=False, behavior=None):
        report = self.report(number, positive=appearance, at=at)
        report['behavior'] = dict(behavior or {})
        report['behavior']['report_context'] = dict(aggregation_policy='peak_frame_v1',
            observed_detection_frames=95, observed_abnormality_frames=17 if appearance else 0,
            abnormality_count_semantics='detections_in_one_peak_frame',
            abnormality_status='observed' if appearance else 'not_observed')
        if appearance:
            report['abnormalities'][0]['count'] = report['abnormalities'][0]['targets']
        return report

    def submit_peak(self, number, *, received_at=None, **fields):
        return self.repo.import_device_report(self.peak_report(number, **fields),
            received_at=received_at or self.now, inbox_cursor=number, now=self.now)

    def test_peak_appearance_uses_only_explicit_evidence_and_distinct_fresh_windows(self):
        self.submit()
        self.now += timedelta(minutes=1)
        first = self.submit_peak(2, appearance=True)['event_id']
        appearance, legacy = sorted(self.service.events(), key=lambda event: event['code'])
        self.assertEqual(appearance['code'], APPEARANCE)
        self.assertEqual(appearance['lifecycle_state'], 'ACTIVE')
        self.assertEqual(legacy['lifecycle_state'], 'INDETERMINATE')
        self.assertEqual(appearance['device_report_event']['labels'][0]['targets'], 46)
        self.ack(appearance)
        self.assertEqual(self.submit_peak(3, appearance=True)['status'], 'same_window')
        self.assertEqual(self.repo.device_report_cursor('board-1'), 3)
        self.now += timedelta(minutes=1)
        self.assertEqual(self.submit_peak(4, appearance=True)['event_id'], first)
        event = next(item for item in self.service.events() if item['id'] == first)
        self.assertEqual(event['last_batch_id'], 'report-4')
        self.assertEqual(event['handling']['state'], 'ACKNOWLEDGED')
        self.now += timedelta(minutes=1)
        report = self.peak_report(5)
        report['has_abnormality'] = True  # Can mean the old behavior snapshot alone.
        self.assertEqual(self.repo.import_device_report(report, received_at=self.now,
            inbox_cursor=5, now=self.now)['status'], 'no_signal')
        event = next(item for item in self.service.events() if item['id'] == first)
        self.assertEqual(event['lifecycle_state'], 'INDETERMINATE')
        self.assertIsNone(event.get('resolved_at'))

    def test_modern_fragments_and_delayed_arrivals_do_not_emit_events(self):
        malformed = self.peak_report(1, appearance=True)
        malformed['report_text'] = '【结果分包 残片'
        self.assertEqual(self.repo.import_device_report(malformed, received_at=self.now,
            inbox_cursor=1, now=self.now)['status'], 'no_signal')
        self.assertEqual(self.service.events(), [])
        self.assertEqual(self.submit_peak(2, appearance=True)['status'], 'accepted')
        self.now += timedelta(seconds=180)
        self.assertEqual(self.submit_peak(3, appearance=True,
            at=self.now-timedelta(seconds=61))['status'], 'no_signal')
        self.assertEqual(len(self.service.events()), 1)
        self.assertEqual(self.service.events()[0]['last_batch_id'], 'report-2')

    def test_video_behavior_without_window_context_cannot_become_legacy_visual_signal(self):
        report = self.report(1, positive=True)
        report['abnormalities'] = []
        report['behavior'] = dict(aggregation_policy='independent_video_results')
        self.assertEqual(self.repo.import_device_report(report, received_at=self.now,
            inbox_cursor=1, now=self.now)['status'], 'no_signal')
        self.assertEqual(self.service.events(), [])

    def test_behavior_version_uses_its_own_clock_and_evidence(self):
        old = dict(report_id='old', result_timestamp=(self.now-timedelta(hours=1)).isoformat(),
            aggregation_policy='independent_video_results', result_semantics='snapshot_not_additive',
            new_result=True, results=[dict(video='old.mp4', is_abnormal=True)])
        self.assertEqual(self.submit_peak(1, behavior=old)['status'], 'no_signal')
        first_end = self.now
        self.now += timedelta(minutes=1)
        new = dict(old, report_id='new', result_timestamp=(self.now-timedelta(seconds=5)).isoformat(),
            new_result=False, results=[dict(video='abnormal.mp4', is_abnormal=True),
                dict(video='normal.mp4', is_abnormal=False)])
        # The board may have prepared a previous packet that never reached the site.
        event_id = self.submit_peak(2, behavior=new)['event_id']
        event = self.current()
        self.assertEqual(event['id'], event_id)
        self.assertEqual(event['code'], BEHAVIOR)
        self.assertEqual(event['occurred_at'], new['result_timestamp'])
        self.assertEqual(event['device_report_event']['abnormal_videos'], ['abnormal.mp4'])
        self.now += timedelta(minutes=1)
        self.assertEqual(self.submit_peak(3, behavior=dict(new, new_result=True))['status'], 'no_signal')
        out_of_order = dict(new, report_id='out-of-order', result_timestamp=(first_end+timedelta(seconds=12)).isoformat())
        self.now += timedelta(seconds=1)
        self.assertEqual(self.submit_peak(4, behavior=out_of_order)['status'], 'no_signal')
        self.assertEqual(len(self.service.events()), 1)

    def test_gap_requires_established_stream_and_resumes_on_fresh_window(self):
        self.submit_peak(1)
        for number in (2, 3):
            self.now += timedelta(minutes=1)
            self.assertIsNone(self.repo.check_device_report_gap('board-1', now=self.now))
            self.submit_peak(number)
        last_valid = self.now
        self.now += timedelta(seconds=179)
        self.assertIsNone(self.repo.check_device_report_gap('board-1', now=self.now))
        self.now += timedelta(seconds=1)
        gap_id = self.repo.check_device_report_gap('board-1', now=self.now)
        self.assertIsNotNone(gap_id)
        restarted = MonitoringRepository(self.repo.path, require_existing=True)
        self.assertEqual(restarted.check_device_report_gap('board-1', now=self.now), gap_id)
        self.submit_peak(4, at=last_valid+timedelta(seconds=60))
        self.assertEqual(self.current()['lifecycle_state'], 'ACTIVE')
        self.assertEqual(self.current()['code'], GAP)
        self.assertEqual(self.current()['current_data_quality']['connectivity'], 'unknown')
        invalid = self.peak_report(5)
        invalid['behavior']['report_context']['observed_detection_frames'] = 0
        self.repo.import_device_report(invalid, received_at=self.now, inbox_cursor=5, now=self.now)
        self.assertEqual(self.current()['lifecycle_state'], 'ACTIVE')
        self.submit_peak(6)
        self.assertEqual(self.current()['id'], gap_id)
        self.assertEqual(self.current()['lifecycle_state'], 'RESOLVED')
        self.assertEqual(self.current()['state_reason'], 'DEVICE_REPORT_UPDATES_RESUMED')
        self.assertEqual(self.current()['device_report_event']['resumed_window_end'], self.now.isoformat())
        self.now += timedelta(minutes=4)
        self.assertIsNone(self.repo.check_device_report_gap('board-1', now=self.now))


if __name__=='__main__':unittest.main()
