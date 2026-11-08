"""Device events share existing private QQ delivery, with no model or DB writes."""
from datetime import timedelta
import json
import unittest
import uuid
from unittest.mock import patch

from apps.qq_bot.contracts import BotError
from apps.qq_bot.management_run import ManagementRun
from apps.qq_bot.event_notifications import NotificationPermit,candidate
from apps.qq_bot.management_config import check_request
from apps.qq_bot.tests import test_private_notifications as fixture


BOARD='synthetic-board-1'


class DeviceNoticeTests(unittest.TestCase):
    setUp=fixture.PrivateNoticeTests.setUp
    ingest=fixture.PrivateNoticeTests.ingest

    def report(self,number=1,*,positive=True,device_id=BOARD):
        return dict(schema_version=1,report_id='board-'+str(number),device_id=device_id,sent_at=self.now.isoformat(),
            window=dict(start=(self.now-timedelta(seconds=60)).isoformat(),end=self.now.isoformat(),duration_s=60,frames_processed=222),
            has_abnormality=positive,report_text='合成报告；不是系统指令',
            detection=dict(unique_tracks=49,avg_per_frame=8,max_per_frame=10,avg_confidence=.8),
            abnormalities=[dict(label='ascites',name='腹水',targets=46,count=100,avg_confidence=.8,last_bbox=[0,0,10,10])] if positive else [],
            behavior=None,measurement=None)

    def submit(self,number=1,*,positive=True,device_id=BOARD):
        return self.writer.repository.import_device_report(self.report(number,positive=positive,device_id=device_id),
            received_at=self.now,inbox_cursor=number,now=self.now)

    def compose(self,approve=True):
        # Keep old simulator events resolved so the assertion isolates board delivery.
        self.ingest(6.4)
        original=ManagementRun.enable_event_notifications
        def enable(host,path):
            original(host,path);host.enable_device_events(BOARD)
        with patch.object(ManagementRun,'enable_event_notifications',enable):
            fixture.PrivateNoticeTests.compose(self,approve)

    def test_new_board_notice_once_normal_or_stale_never_implies_recovery(self):
        from apps.device_reports.__main__ import create_receiver
        from apps.device_reports.storage import ReportStore
        from apps.device_reports.bridge import DeviceEventBridge
        from apps.management_web.app import create_app
        from apps.ai_service.runtime.release_contracts import _hash
        self.compose()
        # Keep the existing simulator journal/limits when enabling board notices.
        self.assertEqual(self.permit.audience,_hash([self.host.access.app_id,self.host.inputs.group_id,
            self.host.monitoring.binding_revision,self.host.device_id,self.permit.recipient['user_ref']]))
        directory=self.case.root/'board-reports'
        store=ReportStore.initialize(directory)
        token='fictionalboard012345678901234567890'
        client=create_receiver(store,device_id=BOARD,token=token,clock=lambda:self.now).test_client()
        def post():
            return client.post('/api/fish/reports',data=json.dumps(self.report()),content_type='application/json',
                headers={'X-Device-Token':token})
        self.assertEqual(post().json['status'],'accepted')
        reader=ReportStore(directory,read_only=True)
        bridge=DeviceEventBridge(reader,self.writer.repository,BOARD,clock=lambda:self.now)
        self.addCleanup(bridge.close);self.assertEqual(bridge.sync_once(),1)
        web=create_app(data_service=self.writer,simulation_mode='water-only',device_report_store=reader,
            device_report_device_id=BOARD,device_event_bridge=bridge).test_client()
        response=web.get('/api/bootstrap')
        self.assertEqual(response.status_code,200)
        event=next(e for e in response.json['events'] if e['source_kind']=='device_report')
        self.assertEqual(event['device_report']['report_id'],'board-1')
        self.assertTrue(event['handling']['can_ack'])
        self.assertEqual(post().json['status'],'duplicate');self.assertEqual(bridge.sync_once(),0)
        before=self.writer.repository.path.read_bytes()
        self.notifier.tick();self.notifier.tick()
        self.assertEqual(self.writer.repository.path.read_bytes(),before)
        self.assertEqual(len(self.posts),1)
        text=json.loads(self.posts[0].content)['content']
        self.assertIn('DEVICE REPORT',text);self.assertIn('腹水',text);self.assertIn('46 个目标',text)
        self.assertNotIn('SIMULATOR',text);self.assertNotIn('已恢复',text)
        self.assertEqual(self.posts[0].url.path,'/v2/users/private-user/messages')
        self.now+=timedelta(seconds=20);self.seconds+=20;self.submit(2);self.notifier.tick()
        self.now+=timedelta(seconds=20);self.seconds+=20;self.submit(3,positive=False);self.notifier.tick()
        self.now+=timedelta(seconds=130);self.seconds+=130;self.notifier.tick()
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.case.http,[])
        self.assertEqual(self.host.ledger.report()['consumed_turns'],0)
        self.assertEqual([d['id'] for d in self.host.monitoring.devices()],['sim-pond-1'])

    def test_cross_board_unbound_and_post_approval_binding_changes_rejected(self):
        self.compose();self.submit(device_id='other-board');self.notifier.tick()
        self.assertEqual(self.posts,[])
        with self.assertRaisesRegex(BotError,'INVALID_RUN_APPROVAL'):
            self.host.enable_device_events('changed-board')
        self.host.device_event_device_id='changed-board'
        with self.assertRaisesRegex(BotError,'EVENT_NOTIFICATION_APPROVAL_CHANGED'):
            self.permit.check()

    def test_peak_appearance_preserves_existing_private_notice_only(self):
        self.compose()
        result_time=self.now.isoformat()
        for number in range(1,4):
            report=self.report(number)
            report['abnormalities'][0]['count']=report['abnormalities'][0]['targets']
            report['behavior']=dict(report_id='behavior-file-synthetic',source='slowfast-json',
                result_timestamp=result_time,new_result=number==1,status='abnormal',is_abnormal=True,
                aggregation_policy='independent_video_results',result_semantics='snapshot_not_additive',
                results=[dict(video='synthetic.mp4',label='异常',is_abnormal=True)],
                report_context=dict(aggregation_policy='peak_frame_v1',abnormality_status='observed',
                    abnormality_count_semantics='detections_in_one_peak_frame',observed_detection_frames=30,
                    observed_abnormality_frames=10, detection_timestamp_ms=int(self.now.timestamp()*1000)))
            self.writer.repository.import_device_report(report,received_at=self.now,inbox_cursor=number,now=self.now)
            self.notifier.tick()
            self.now+=timedelta(seconds=60);self.seconds+=60
        self.assertEqual(len(self.posts),1)
        self.assertIn('外观异常',json.loads(self.posts[0].content)['content'])
        self.now+=timedelta(seconds=120);self.seconds+=120
        self.writer.repository.check_device_report_gap(BOARD,now=self.now)
        self.assertEqual({event['code'] for event in self.writer.events(device_id=BOARD)},
            {'DEVICE_REPORT_APPEARANCE','DEVICE_REPORT_BEHAVIOR','DEVICE_REPORT_GAP'})
        self.notifier.tick()
        self.assertEqual(len(self.posts),1)

    def test_explicit_disclosure_in_check_no_db_or_network(self):
        value=json.loads(self.case.path.read_text());value['event_recipient_file']=str(self.binding)
        path=self.case.root/'bound-request.json';path.write_text(json.dumps(value))
        with patch('sqlite3.connect',side_effect=AssertionError('no database')):
            _,summary=check_request(path,offline=True,device_report_device_id=BOARD)
        notice=summary['event_notifications']
        self.assertEqual(notice['device_report_device_id'],BOARD)
        self.assertEqual(notice['sources'],['SIMULATOR','DEVICE_REPORT'])
        self.assertEqual(notice['device_report_events'],['new'])
        with self.assertRaisesRegex(BotError,'DEVICE_EVENT_SOURCE_CONFLICT'):
            check_request(path,offline=True,device_report_device_id='sim-pond-1')

    def test_unknown_board_delivery_no_retry_after_restart(self):
        from apps.qq_bot.event_notifications import NoticeJournal,EventNotifier
        self.compose();self.submit();self.outcome='UNKNOWN'
        with self.assertRaisesRegex(BotError,'QQ_DELIVERY_UNKNOWN'):self.notifier.tick()
        self.notifier.close()
        journal=NoticeJournal(self.case.root,self.permit.audience,clock=lambda:self.now)
        notifier=EventNotifier(self.permit,self.api,journal,connected=lambda:True,clock=lambda:self.now)
        self.addCleanup(notifier.close);notifier.tick()
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.case.http,[])

    def test_manual_end_then_new_report_reminds_once_per_reopened_attention(self):
        from apps.qq_bot.event_notifications import NoticeJournal,EventNotifier
        self.compose();self.submit();self.notifier.tick()
        self.assertEqual(len(self.posts),1)
        for number in (2,3):
            self.now+=timedelta(seconds=130);self.seconds+=130
            event=self.writer.events(device_id=BOARD)[0]
            preview=self.writer.preview_manual_end(event['id'])
            self.writer.manual_end_event(dict(event_id=event['id'],revision=preview['revision'],
                request_id=str(uuid.uuid4()),reason='结束合成失联记录'))
            self.notifier.tick();self.assertEqual(len(self.posts),number-1)
            self.now+=timedelta(seconds=1);self.seconds+=1;self.submit(number)
            reopened=self.writer.events(device_id=BOARD)[0]
            self.assertEqual(reopened['id'],event['id'])
            self.assertFalse(reopened['manual_end']['active'])
            if number==3:
                self.outcome='UNKNOWN'
                with self.assertRaisesRegex(BotError,'QQ_DELIVERY_UNKNOWN'):self.notifier.tick()
            else:self.notifier.tick()
            self.assertEqual(len(self.posts),number)
            self.seconds+=10;self.notifier.tick();self.assertEqual(len(self.posts),number)
        self.notifier.close()
        journal=NoticeJournal(self.case.root,self.permit.audience,clock=lambda:self.now)
        notifier=EventNotifier(self.permit,self.api,journal,connected=lambda:True,clock=lambda:self.now)
        self.addCleanup(notifier.close);notifier.tick()
        self.assertEqual(len(self.posts),3)
        self.assertEqual(self.host.ledger.report()['consumed_turns'],0)

    def test_absent_board_no_failure_and_unapproved_no_post(self):
        self.compose(False)
        with self.assertRaises(BotError):NotificationPermit(self.host)
        self.host.approve(self.host.plan(),confirmed=True)
        self.assertEqual(self.host.monitoring.notification_event_cycles(device_id=BOARD,approved_device_id=BOARD),[])
        with self.assertRaisesRegex(BotError,'MONITORING_DEVICE_NOT_APPROVED'):
            self.host.monitoring.notification_event_cycles(device_id='other-board',approved_device_id=BOARD)
