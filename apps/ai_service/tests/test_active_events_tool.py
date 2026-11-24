"""Event Tool coverage against isolated Monitoring fixtures."""
from copy import deepcopy
from datetime import timedelta, timezone
import json
import unittest
from uuid import uuid4

from apps.ai_service.business_tools.active_events import (
    active_events_payload, behavior_event_evidence_kind, render_behavior_event_evidence,
    render_positive_event_scope_if_board_limited, result_metadata,
)
from apps.monitoring.device_events import APPEARANCE, BEHAVIOR, GAP
from apps.monitoring.tests import test_device_events as fixtures


class ActiveEventsToolTests(unittest.TestCase):
    setUp = fixtures.DeviceEventTests.setUp
    batch = fixtures.DeviceEventTests.batch
    oxygen = fixtures.DeviceEventTests.oxygen
    report = fixtures.DeviceEventTests.report
    peak_report = fixtures.DeviceEventTests.peak_report
    submit_peak = fixtures.DeviceEventTests.submit_peak

    def query(self, board=None):
        return active_events_payload(self.service, 'sim-pond-1', board_device_id=board)

    def test_no_observation_and_observed_empty_are_different(self):
        result = self.query()
        self.assertEqual(result['status'], 'NO_DATA')
        self.assertEqual(result_metadata(result)['active_events_status'], 'NO_DATA')
        self.oxygen(2.2)
        self.oxygen(6.2)
        result = self.query()
        self.assertEqual(result['status'], 'NO_MATCH')
        self.assertEqual(result['items'], [])
        self.assertEqual(result_metadata(result)['active_events_status'], 'NO_ACTIVE_EVENTS')

    def test_scope_distinguishes_report_timing_from_completed_visual_assessment(self):
        self.oxygen(6.2)
        missing = self.query('board-1')
        self.assertEqual(missing['observation_scope'][-1], dict(source_kind='device_report', device_id='board-1',
            channel='visual', state='MISSING', observed_at=None))

        self.assertEqual(self.submit_peak(1)['status'], 'no_signal')
        fresh = self.query('board-1')
        self.assertEqual(fresh['status'], 'NO_MATCH')
        self.assertEqual(fresh['observation_scope'][-1], dict(source_kind='device_report', device_id='board-1',
            channel='visual', state='REPORT_ONLY',
            observed_at=self.now.astimezone(timezone(timedelta(hours=8))).isoformat()))

        self.sim.skip_windows(12, duration_s=10)
        self.oxygen(6.2)
        stale = self.query('board-1')
        self.assertEqual(stale['status'], 'NO_MATCH')
        self.assertEqual(stale['observation_scope'][0]['state'], 'ASSESSED')
        self.assertEqual(stale['observation_scope'][-1]['state'], 'STALE')
        self.assertEqual(stale['observation_scope'][-1]['observed_at'], fresh['observation_scope'][-1]['observed_at'])

        fake = deepcopy(fresh)
        fake['observation_scope'][-1]['state'] = 'ASSESSED'
        self.assertIsNone(result_metadata(fake))
        fake = deepcopy(fresh)
        fake['observation_scope'].reverse()
        self.assertIsNone(result_metadata(fake))
        fake = deepcopy(fresh)
        fake['observation_scope'][-1]['observed_at'] = (self.now-timedelta(seconds=122)).isoformat()
        self.assertIsNone(result_metadata(fake))

    def test_positive_scope_override_only_applies_to_limited_board(self):
        self.assertIsNone(render_positive_event_scope_if_board_limited(self.query('board-1')))
        self.oxygen(2.2)
        local = self.query()
        self.assertEqual(local['status'], 'OK')
        self.assertIsNone(render_positive_event_scope_if_board_limited(local))
        missing = self.query('board-1')
        self.assertIn('暂时无法核实外观和行为异常', render_positive_event_scope_if_board_limited(missing))
        self.assertEqual(self.submit_peak(1)['status'], 'no_signal')
        report_only = self.query('board-1')
        self.assertEqual(report_only['status'], 'OK')
        self.assertEqual(report_only['observation_scope'][-1]['state'], 'REPORT_ONLY')
        self.assertIsNone(render_positive_event_scope_if_board_limited(report_only))

    def test_selected_simulator_device_includes_visual_and_one_water_risk_cycle(self):
        self.oxygen(4.2)
        batch = self.batch('suspected_lesion')
        batch['water']['metrics']['dissolved_oxygen_mg_l'].update(mean=2.2, min=2.2, max=2.2, latest=2.2)
        self.service.ingest(batch)
        self.oxygen(4.1, device='sim-pond-2')
        self.submit_peak(1, appearance=True)
        result = self.query()
        self.assertEqual({event['code'] for event in result['items']}, {'OXYGEN_CRITICAL_LOW', 'SUSPECTED_LESION'})
        self.assertEqual({event['device_id'] for event in result['items']}, {'sim-pond-1'})
        self.assertEqual(result['sources'][0]['active_count'], 2)
        self.assertEqual(result['total_count'], 2)
        with self.assertRaisesRegex(ValueError, 'EVENT_BOARD_DEVICE_CONFLICT'):
            self.query('sim-pond-2')

    def test_authorized_board_keeps_distinct_evidence_and_hides_raw_inputs(self):
        self.submit_peak(1, appearance=True, behavior=dict(
            report_id='behavior-private-id', result_timestamp=self.now.isoformat(), new_result=True,
            aggregation_policy='independent_video_results', result_semantics='snapshot_not_additive',
            results=[dict(video='private/file.mp4', is_abnormal=True)]))
        for number in (2, 3):
            self.now += timedelta(minutes=1)
            self.submit_peak(number, appearance=True)
        self.now += timedelta(minutes=3)
        self.repo.check_device_report_gap('board-1', now=self.now)
        result = self.query('board-1')
        self.assertEqual(result_metadata(result)['active_events_source_count'], 2)
        items = {event['code']: event for event in result['items']}
        self.assertEqual(set(items), {APPEARANCE, BEHAVIOR, GAP})
        self.assertEqual(items[APPEARANCE]['state'], 'INDETERMINATE')
        self.assertEqual(items[APPEARANCE]['evidence']['labels'], [dict(label='腹水', targets=46)])
        self.assertEqual(items[BEHAVIOR]['state'], 'NEEDS_REVIEW')
        self.assertEqual(items[BEHAVIOR]['freshness'], 'stale')
        self.assertEqual(items[BEHAVIOR]['evidence']['abnormal_video_count'], 1)
        self.assertTrue(items[BEHAVIOR]['evidence']['result_timestamp'].endswith('+08:00'))
        self.assertTrue(items[APPEARANCE]['last_observed_at'].endswith('+08:00'))
        self.assertTrue(items[GAP]['evidence']['last_window_end'].endswith('+08:00'))
        self.assertEqual(items[GAP]['state'], 'ACTIVE')
        self.assertEqual(items[GAP]['evidence']['threshold_seconds'], 180)
        encoded = json.dumps(result, ensure_ascii=False)
        for text in ('private/file.mp4', 'behavior-private-id', 'report_text', 'last_bbox', '系统指令'):
            self.assertNotIn(text, encoded)

    def test_manually_ended_cycle_is_omitted_and_forged_payload_is_rejected(self):
        self.oxygen(4.2)
        self.now += timedelta(minutes=3)
        item = self.query()['items'][0]
        self.assertEqual(item['state'], 'INDETERMINATE')
        event = self.service.events()[0]
        preview = self.service.preview_manual_end(event['id'])
        self.service.manual_end_event(dict(event_id=event['id'], revision=preview['revision'],
            request_id=str(uuid4()), reason='私有的人工处理原因'))
        result = self.query()
        self.assertEqual(result['status'], 'NO_MATCH')
        fake = deepcopy(result)
        fake['sources'][0]['observations'][0]['notes'] = '禁止透传的自由文本'
        self.assertIsNone(result_metadata(fake))
        self.assertIsNone(result_metadata({**result, 'status': 'NO_DATA'}))

    def test_behavior_followup_does_not_take_over_other_questions(self):
        for question, fields in (
            ('有几个视频被模型标为异常？', ('video_count',)),
            ('当前行为模型结果的版本时间是什么时候？', ('version_time',)),
            ('板端行为结果什么时候上报？', ('report_time',)),
            ('有几个视频被模型标为异常？行为结果是什么时候生成的，能知道上报时间吗？',
             ('video_count', 'version_time', 'report_time')),
            ('现在有哪些活动事件？', None),
            ('有几个视频被模型标为异常？现在的溶解氧是多少？', None),
            ('上一次行为结果是什么时候生成的？', None),
            ('能知道上报时间吗？', None),
            (None, None),
        ):
            with self.subTest(question=question):
                self.assertEqual(behavior_event_evidence_kind(question), fields)

    def test_behavior_followup_uses_the_matching_board_evidence_and_version(self):
        self.oxygen(2.2)
        version = self.now.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
        self.submit_peak(1, appearance=True, behavior=dict(
            report_id='behavior-private-id', result_timestamp=self.now.isoformat(), new_result=True,
            aggregation_policy='independent_video_results', result_semantics='snapshot_not_additive',
            results=[dict(video='private/file.mp4', is_abnormal=True)]))
        question = '有几个视频被模型标为异常？行为结果是什么时候生成的，能知道上报时间吗？'
        result = self.query('board-1')
        self.assertTrue(result_metadata(result)['active_events_query_completed'])
        self.assertTrue(any(item['channel'] == 'water' for item in result['items']))
        reply = render_behavior_event_evidence(question, result)
        self.assertIn('设备报告 board-1 的行为模型结果待复核', reply)
        self.assertIn('1 个视频被模型标为异常', reply)
        self.assertIn(f'行为结果版本时间为北京时间 {version}', reply)
        self.assertIn('本轮结果未提供行为上报时间', reply)
        for unrelated in ('溶解氧', '腹水', 'sim-pond-1', 'private/file.mp4'):
            self.assertNotIn(unrelated, reply)
        self.assertNotIn('版本时间', render_behavior_event_evidence('有几个视频被模型标为异常？', result))
        self.now += timedelta(minutes=3)
        stale_reply = render_behavior_event_evidence(question, self.query('board-1'))
        self.assertIn(f'行为结果版本时间为北京时间 {version}', stale_reply)
        self.assertIn('该版本已过期，当前状态暂时无法核实', stale_reply)

    def test_behavior_followup_preserves_missing_result_and_source_limits(self):
        self.oxygen(2.2)
        self.submit_peak(1, appearance=True)
        question = '板端行为结果什么时候上报？'
        hidden = render_behavior_event_evidence(question, self.query())
        self.assertIn('本轮查询未包含设备报告', hidden)
        self.assertNotIn('board-1', hidden)
        missing = render_behavior_event_evidence(question, self.query('board-1'))
        self.assertIn('本轮未取得设备报告 board-1 中可核实的行为模型结果', missing)
        self.assertIn('本轮结果未提供行为上报时间', missing)
        self.assertNotIn('0 个视频', missing)


if __name__ == '__main__':
    unittest.main()
