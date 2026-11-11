"""Event Tool coverage against isolated Monitoring fixtures."""
from copy import deepcopy
from datetime import timedelta
import json
import unittest
from uuid import uuid4

from apps.ai_service.business_tools.active_events import active_events_payload, result_metadata
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


if __name__ == '__main__':
    unittest.main()
