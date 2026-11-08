"""Synthetic multipart transport and read-only display tests, no device access."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from apps.device_reports.presentation import recent_view, project_reports, MAX_SCAN_PACKETS, MAX_TASK_ITEMS
from apps.device_reports.storage import ReportStore

NOW = datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)
DEVICE = 'synthetic-board'
BASE = 'web-' + 'a' * 40


def report():
    return dict(schema_version=1, report_id='single-1', device_id=DEVICE, sent_at=NOW.isoformat(),
        window=dict(start=(NOW-timedelta(seconds=60)).isoformat(), end=NOW.isoformat(), duration_s=60,
                    frames_processed=2),
        detection=dict(unique_tracks=12, avg_per_frame=6, max_per_frame=12, avg_confidence=0),
        has_abnormality=True,
        abnormalities=[dict(label='ascites', name='疑似腹水', targets=2, count=2, avg_confidence=.56,
                            last_bbox=[1, 2, 3, 4])],
        report_text='synthetic original report', measurement=None, behavior=None)


def original():
    return dict(device_id=DEVICE, inputs=dict(measurement=dict(source_kind='video_replay',
        capture_timestamp='2026-11-06T10:55:51+00:00', measurement=dict(status='success',
            fish_detected=3, fish_measured=1, fish_uncertain=1, fish_skipped=1,
            calibration_status='unverified_camera_and_depth', measurement_note='毫米值为未标定估计',
            fishes=[dict(display_id='F01', length_px=532.2, length_mm=240.2, physical_length_mm=None,
                         status='measured_unverified', status_text='未标定估计', quality_warnings=[]),
                    dict(display_id='F02', length_px=None, length_mm=None, physical_length_mm=None,
                         status_text='画面截断'),
                    dict(display_id='F03', length_px=100, length_mm=90, physical_length_mm=None,
                         status_text='需复核', quality_warnings=['possible_instance_overlap'])])),
        behavior=dict(source_kind='video_replay', capture_timestamp='2026-11-06T10:55:55+00:00',
            behavior=dict(source='synthetic-behavior', anomalous=2, clips=[
                dict(start_s=0, end_s=1.2, score=4.8, anomaly=True),
                dict(start_s=.6, end_s=1.8, score=5.0, anomaly=True)])),
        detection=dict(timestamp=int(NOW.timestamp()*1000), count=1)))


def item(value):
    return dict(report=value, received_at=NOW.isoformat(), freshness='stale', warnings=[])


def packets(document=None, *, source=None, base=BASE, total=4):
    if document is None:
        document = '各任务时间独立\n【完整原始 JSON】\n' + json.dumps(original() if source is None else source, ensure_ascii=False)
    digest = hashlib.sha256(document.encode('utf-8')).hexdigest()
    # Preserve all leading/trailing fragment whitespace and non-ASCII characters.
    width = max(1, (len(document) + total - 1) // total)
    fragments = [document[i*width:(i+1)*width] for i in range(total)]
    result = []
    for index, fragment in enumerate(fragments, 1):
        value = report()
        value.update(report_id=f'{base}-{index}',
            report_text=f'【结果分包 {index}/{total}；SHA256={digest}】\n{fragment}',
            measurement=dict(delivery='full_result_in_report_text', source_sha256='b'*64))
        result.append(item(value))
    return result


class PresentationTests(unittest.TestCase):
    def test_four_out_of_order_packets_merge_without_changing_raw(self):
        values = packets()
        before = copy.deepcopy(values)
        projected = project_reports([values[2], values[3], values[0], values[1]])
        self.assertEqual(len(projected), 1)
        value = projected[0]
        self.assertEqual(value['report']['report_id'], BASE)
        self.assertEqual(value['assembly'], dict(status='complete', received_parts=4, total_parts=4, issue_codes=[]))
        self.assertEqual(value['freshness'], 'stale')
        self.assertEqual(len(value['raw_parts']), 4)
        self.assertTrue(value['report']['report_text'].startswith('各任务时间独立'))
        self.assertEqual(values, before)

    def test_task_times_estimate_quality_and_overlap_remain_distinct(self):
        view = project_reports(packets())[0]['presentation']
        self.assertEqual(view['detection']['unique_tracks'], 12)
        self.assertEqual(view['detection']['frames_processed'], 2)
        self.assertEqual(view['detection']['avg_confidence'], 0)
        measurement, behavior = view['measurement'], view['behavior']
        self.assertEqual(measurement['counts']['fish_detected'], 3)
        self.assertIsNone(measurement['counts']['fish_computed'])
        self.assertEqual(measurement['source_kind'], 'video_replay')
        self.assertEqual(measurement['calibration_status'], 'unverified_camera_and_depth')
        self.assertEqual(measurement['fishes'][0]['length_mm'], 240.2)
        self.assertEqual(measurement['fishes'][0]['length_px'], 532.2)
        self.assertIsNone(measurement['fishes'][0]['physical_length_mm'])
        self.assertIsNone(measurement['fishes'][1]['length_mm'])
        self.assertEqual(measurement['fishes'][1]['status_text'], '画面截断')
        self.assertEqual(measurement['fishes'][2]['quality_warnings'], ['possible_instance_overlap'])
        self.assertNotEqual(measurement['captured_at'], behavior['captured_at'])
        self.assertEqual(behavior['anomalous_clips'], 2)
        self.assertEqual(behavior['clip_count'], 2)
        self.assertEqual(behavior['clips'][1]['start_s'], .6)
        self.assertEqual(behavior['clips'][0]['score'], 4.8)

    def test_incomplete_packets_do_not_parse_half_json_or_present_tasks_as_complete(self):
        value = project_reports(packets()[:2])[0]
        self.assertEqual(value['assembly']['status'], 'incomplete')
        self.assertEqual(value['assembly']['received_parts'], 2)
        self.assertEqual(value['report']['report_text'], '')
        self.assertEqual(value['presentation']['measurement']['status'], 'pending')
        self.assertEqual(value['presentation']['behavior']['status'], 'pending')
        self.assertEqual(len(value['raw_parts']), 2)

    def test_duplicate_part_does_not_add_logical_result(self):
        values = packets()
        value = project_reports(values + [copy.deepcopy(values[0])])[0]
        self.assertEqual(value['assembly']['status'], 'complete')
        self.assertEqual(value['assembly']['received_parts'], 4)

    def test_wrong_sha_is_invalid_without_discarding_raw_parts(self):
        values = packets()
        values[2]['report']['report_text'] += 'tampered'
        value = project_reports(values)[0]
        self.assertEqual(value['assembly']['status'], 'invalid')
        self.assertIn('ASSEMBLED_HASH_MISMATCH', value['assembly']['issue_codes'])
        self.assertEqual(len(value['raw_parts']), 4)
        self.assertEqual(value['presentation']['measurement']['status'], 'pending')

    def test_metadata_hash_total_and_index_conflicts_fail_display_only(self):
        mutations = (
            lambda v: v[1]['report']['detection'].update(unique_tracks=999),
            lambda v: v[1]['report'].update(report_text=v[1]['report']['report_text'].replace('SHA256=', 'SHA256=f')),
            lambda v: v[1]['report'].update(report_text=v[1]['report']['report_text'].replace('2/4', '2/5')),
            lambda v: v[1]['report'].update(report_text=v[1]['report']['report_text'].replace('2/4', '3/4')),
        )
        for change in mutations:
            with self.subTest(change=change):
                values = packets(); change(values)
                value = project_reports(values)[0]
                self.assertEqual(value['assembly']['status'], 'invalid')
                self.assertTrue(value['assembly']['issue_codes'])
                self.assertEqual(len(value['raw_parts']), 4)

    def test_conflicting_duplicate_content_is_invalid(self):
        values = packets()
        duplicate = copy.deepcopy(values[0]); duplicate['report']['report_text'] += 'different'
        value = project_reports(values+[duplicate])[0]
        self.assertIn('PART_CONTENT_CONFLICT', value['assembly']['issue_codes'])

    def test_same_window_different_report_or_device_never_merge(self):
        values = packets() + packets(base='web-'+'b'*40)
        other = packets()
        for part in other: part['report']['device_id'] = 'another-board'
        projected = project_reports(values+other)
        self.assertEqual(len(projected), 3)
        self.assertEqual([len(v['raw_parts']) for v in projected], [4, 4, 4])

    def test_header_and_assembly_size_limits_retain_raw(self):
        for values, code in ((packets(total=33), 'PART_LIMIT_OR_INDEX_INVALID'),
                             (packets(document='x'*(256*1024+1), total=32), 'ASSEMBLED_DOCUMENT_TOO_LARGE')):
            with self.subTest(code=code):
                value = project_reports(values)[0]
                self.assertEqual(value['assembly']['status'], 'invalid')
                self.assertIn(code, value['assembly']['issue_codes'])
                self.assertEqual(len(value['raw_parts']), len(values))

    def test_unrecognized_header_never_shows_assembled_content(self):
        value = report(); value['report_text'] = '【结果分包 broken】\nnot a complete document'
        projected = project_reports([item(value)])[0]
        self.assertEqual(projected['assembly']['status'], 'invalid')
        self.assertIn('PART_HEADER_INVALID', projected['assembly']['issue_codes'])
        self.assertEqual(projected['report']['report_text'], '')

    def test_huge_header_integer_cannot_crash_projection(self):
        values = packets()
        values[0]['report']['report_text'] = '【结果分包 '+('9'*6000)+'/4；SHA256='+('a'*64)+'】\ntext'
        projected = project_reports(values)[0]
        self.assertEqual(projected['assembly']['status'], 'invalid')
        self.assertIn('PART_HEADER_INVALID', projected['assembly']['issue_codes'])

    def test_source_and_capture_can_be_nested_in_measurement_result(self):
        source = original()
        packet = source['inputs']['measurement']
        packet['measurement']['source_kind'] = packet.pop('source_kind')
        packet['measurement']['capture_timestamp'] = packet.pop('capture_timestamp')
        value = project_reports(packets(source=source))[0]['presentation']['measurement']
        self.assertEqual(value['source_kind'], 'video_replay')
        self.assertEqual(value['captured_at'], '2026-11-06T10:55:51+00:00')

    def test_legacy_nonmultipart_null_and_unknown_task_objects(self):
        value = report(); value['measurement'] = {'unexpected': 1}
        value['report_text'] = '<script>not HTML</script>'
        projected = project_reports([item(value)])[0]
        self.assertEqual(projected['assembly']['status'], 'single')
        self.assertEqual(projected['presentation']['measurement']['status'], 'unrecognized')
        self.assertEqual(projected['presentation']['behavior']['status'], 'missing')
        self.assertEqual(projected['report']['report_text'], value['report_text'])

    def test_single_known_task_objects_work_without_embedded_document(self):
        value = report(); value.update(original()['inputs'])
        # Detection remains the canonical window statistics, not a raw per-frame object.
        value['detection'] = report()['detection']
        projected = project_reports([item(value)])[0]['presentation']
        self.assertEqual(projected['measurement']['status'], 'available')
        self.assertEqual(projected['behavior']['status'], 'available')

    def test_peak_frame_video_snapshot_keeps_window_and_result_times_separate(self):
        value = report()
        result_time = (NOW - timedelta(hours=2)).isoformat()
        value['behavior'] = dict(
            source='slowfast-json', report_id='behavior-file-fixture', result_timestamp=result_time,
            aggregation_policy='independent_video_results', status='abnormal', is_abnormal=True,
            new_result=False, result_semantics='snapshot_not_additive',
            report_context=dict(aggregation_policy='peak_frame_v1', detection_frame_id=10,
                detection_timestamp_ms=12345, observed_detection_frames=3, abnormality_status='observed',
                abnormality_timestamp_ms=12340, abnormality_frame_id=9, observed_abnormality_frames=7,
                abnormality_count_semantics='detections_in_one_peak_frame'),
            results=[dict(video='fixture-a.mp4', label='异常', is_abnormal=True, rise_z=-0.5, num_clips=4),
                     dict(video='fixture-b.mp4', label='非异常', is_abnormal=False, rise_z=0),
                     dict(video='fixture-c.mp4', is_abnormal='false', num_clips=True)])
        value['measurement'] = dict(report_id='measurement-fixture', created_at=NOW.isoformat(),
            new_result=True, fishes=[dict(display_id='F1', body_incomplete=True, fish_id=1,
                length_mm=25, length_mm_raw=10, length_scale_factor=2.5, physical_length_mm=None)])
        received = item(value)
        received['received_at'] = (NOW+timedelta(seconds=2)).isoformat()
        result = project_reports([received])[0]
        self.assertEqual(result['receive_delay_seconds'], 2)
        self.assertEqual(result['raw_parts'][0]['sent_at'], value['sent_at'])
        view = result['presentation']
        detection = view['detection']
        self.assertEqual(detection['aggregation_policy'], 'peak_frame_v1')
        self.assertEqual(detection['count_semantics'], 'detections_in_one_peak_frame')
        self.assertEqual(detection['report_context'], value['behavior']['report_context'])
        self.assertEqual(detection['abnormalities'], value['abnormalities'])
        behavior = view['behavior']
        self.assertEqual(behavior['kind'], 'videos')
        self.assertEqual(behavior['report_id'], 'behavior-file-fixture')
        self.assertEqual(behavior['result_timestamp'], result_time)
        self.assertIsNone(behavior['captured_at'])
        self.assertIs(behavior['new_result'], False)
        self.assertEqual((behavior['video_count'], behavior['anomalous_videos'], behavior['unknown_videos']), (3, 1, 1))
        self.assertEqual(behavior['videos'][0]['video_name'], 'fixture-a.mp4')
        self.assertEqual(behavior['videos'][0]['rise_z'], -0.5)
        self.assertEqual(behavior['videos'][0]['num_clips'], 4)
        self.assertIsNone(behavior['videos'][2]['num_clips'])
        fish = view['measurement']['fishes'][0]
        self.assertEqual(view['measurement']['report_id'], 'measurement-fixture')
        self.assertEqual((fish['length_mm_raw'], fish['length_scale_factor']), (10, 2.5))
        self.assertTrue(fish['body_incomplete'])
        self.assertIsNone(fish['physical_length_mm'])

    def test_peak_context_with_unavailable_behavior_preserves_unknown_counts(self):
        value = report()
        value['behavior'] = dict(status='not_received',
            report_context=dict(aggregation_policy='peak_frame_v1', abnormality_status='not_observed'))
        view = project_reports([item(value)])[0]['presentation']
        self.assertEqual(view['detection']['report_context']['abnormality_status'], 'not_observed')
        behavior = view['behavior']
        self.assertEqual(behavior['kind'], 'videos')
        self.assertEqual(behavior['reported_status'], 'not_received')
        self.assertIsNone(behavior['video_count'])
        self.assertIsNone(behavior['anomalous_videos'])
        self.assertIsNone(behavior['new_result'])

    def test_multipart_conflict_keeps_reconstructable_original_packets(self):
        values = packets()
        for value in values:
            value['report']['behavior'] = dict(opaque=True)
        values[1]['report']['behavior']['opaque'] = 1
        values[1]['report']['sent_at'] = (NOW+timedelta(seconds=1)).isoformat()
        result = project_reports(values)[0]
        self.assertEqual(result['assembly']['status'], 'invalid')
        self.assertIs(type(result['raw_parts'][1]['context']['behavior']['opaque']), int)
        for part, value in zip(result['raw_parts'], values, strict=True):
            actual = {**result['report'], **part.get('context', {}),
                **{key: part[key] for key in ('report_id', 'report_text', 'sent_at')}}
            self.assertEqual(actual, value['report'])

    def test_null_original_task_does_not_fallback_to_old_envelope(self):
        source = original(); source['inputs']['behavior'] = None
        values = packets(source=source)
        for value in values: value['report']['behavior'] = original()['inputs']['behavior']
        self.assertEqual(project_reports(values)[0]['presentation']['behavior']['status'], 'missing')

    def test_bad_embedded_json_or_different_device_keeps_raw_and_marks_unknown(self):
        for document in ('【完整原始 JSON】\n{', '【完整原始 JSON】\n{"device_id":"other","inputs":{}}',
                         '【完整原始 JSON】\n{"device_id":"synthetic-board","inputs":{},"inputs":{}}'):
            value = project_reports(packets(document=document))[0]
            self.assertEqual(value['assembly']['status'], 'complete')
            self.assertIn('ORIGINAL_JSON_UNRECOGNIZED', value['assembly']['issue_codes'])
            self.assertEqual(value['presentation']['measurement']['status'], 'unrecognized')

    def test_task_values_do_not_coerce_booleans_or_missing_into_numbers(self):
        source = original()
        body = source['inputs']['measurement']['measurement']
        body['fish_measured'] = True
        body['fishes'][0].update(length_px='123', length_mm=False, physical_length_mm=-10)
        behavior = source['inputs']['behavior']['behavior']
        behavior['clips'].append(dict(start_s=2, end_s=3, score='bad', anomaly='false'))
        view = project_reports(packets(source=source))[0]['presentation']
        self.assertIsNone(view['measurement']['counts']['fish_measured'])
        self.assertIsNone(view['measurement']['fishes'][0]['length_px'])
        self.assertIsNone(view['measurement']['fishes'][0]['length_mm'])
        self.assertIsNone(view['measurement']['fishes'][0]['physical_length_mm'])
        self.assertEqual(view['behavior']['unknown_clips'], 1)
        self.assertIsNone(view['behavior']['clips'][2]['anomaly'])

    def test_large_opaque_task_integer_cannot_crash_web_projection(self):
        value = report()
        value['measurement'] = dict(fish_detected=10**1000, fishes=[dict(length_px=10**1000)])
        view = project_reports([item(value)])[0]['presentation']['measurement']
        self.assertIsNone(view['counts']['fish_detected'])
        self.assertIsNone(view['fishes'][0]['length_px'])

    def test_task_display_limits_do_not_silently_change_total_or_raw(self):
        source = original()
        source['inputs']['measurement']['measurement']['fishes'] = [dict(fish_id=i) for i in range(120)]
        source['inputs']['behavior']['behavior']['clips'] = [dict(anomaly=True) for _ in range(120)]
        view = project_reports(packets(source=source))[0]['presentation']
        self.assertEqual(len(view['measurement']['fishes']), MAX_TASK_ITEMS)
        self.assertEqual(view['measurement']['total_fishes'], 120)
        self.assertTrue(view['measurement']['display_truncated'])
        self.assertEqual(len(view['behavior']['clips']), MAX_TASK_ITEMS)
        self.assertEqual(view['behavior']['clip_count'], 120)
        self.assertEqual(view['behavior']['anomalous_clips'], 120)
        self.assertTrue(view['behavior']['display_truncated'])

    def test_bounded_scan_and_logical_count(self):
        values = []
        for i in range(MAX_SCAN_PACKETS+1):
            value = report(); value['report_id'] = f'single-{i}'; values.append(item(value))
        projected = project_reports(values)
        self.assertEqual(len(projected), 20)
        self.assertEqual(projected[0]['report']['report_id'], 'single-0')
        self.assertEqual(projected[-1]['report']['report_id'], 'single-19')

    def test_newest_incomplete_does_not_hide_older_complete_report(self):
        projected = project_reports(packets()[:1]+packets(base='web-'+'b'*40))
        self.assertEqual([v['assembly']['status'] for v in projected], ['incomplete', 'complete'])

    def test_store_adds_logical_reports_without_mutating_packets_schema_or_pending(self):
        temporary = Path(__file__).resolve().parents[3]/'outputs'/'test-tmp'
        temporary.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=temporary) as directory:
            store = ReportStore.initialize(directory)
            values = packets()
            for value in values:
                store.receive(json.dumps(value['report']).encode(), device_id=DEVICE, now=NOW)
            before = store.path.read_bytes()
            pending_before = store.pending(DEVICE)
            reader = ReportStore(directory, read_only=True)
            raw_before = reader.recent(DEVICE, now=NOW+timedelta(seconds=180))
            self.assertNotIn('logical_items', raw_before)
            view = recent_view(reader, DEVICE, now=NOW+timedelta(seconds=180))
            self.assertEqual(view['items'], raw_before['items'])
            self.assertEqual(len(view['items']), 4)
            self.assertEqual({v['report']['report_id']: v['report']['report_text'] for v in view['items']},
                             {v['report']['report_id']: v['report']['report_text'] for v in values})
            self.assertEqual(len(view['logical_items']), 1)
            self.assertEqual(view['logical_items'][0]['assembly']['status'], 'complete')
            self.assertEqual(view['logical_items'][0]['freshness'], 'stale')
            self.assertEqual(view['packet_scan_limit'], MAX_SCAN_PACKETS)
            self.assertFalse(view['packet_scan_limited'])
            self.assertEqual(store.pending(DEVICE), pending_before)
            for _ in range(3):
                recent_view(reader, DEVICE, now=NOW+timedelta(days=1))
            self.assertEqual(store.path.read_bytes(), before)
            with store.connection() as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_bootstrap_exposes_additive_projection_with_existing_raw_packets(self):
        from apps.management_web.app import create_app
        from apps.monitoring.repository import MonitoringRepository
        from apps.monitoring.service import MonitoringService
        temporary = Path(__file__).resolve().parents[3]/'outputs'/'test-tmp'
        temporary.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=temporary) as directory:
            root = Path(directory)
            store = ReportStore.initialize(root/'reports')
            for value in packets():
                store.receive(json.dumps(value['report']).encode(), device_id=DEVICE, now=NOW)
            service = MonitoringService(MonitoringRepository(root/'monitoring.sqlite3'), clock=lambda: NOW)
            before = store.path.read_bytes()
            app = create_app(data_service=service, simulation_mode='water-only',
                device_report_store=ReportStore(root/'reports', read_only=True), device_report_device_id=DEVICE)
            response = app.test_client().get('/api/bootstrap')
            self.assertEqual(response.status_code, 200)
            inbox = response.json['integration']['device_reports']
            self.assertEqual(len(inbox['items']), 4)
            self.assertEqual(len(inbox['logical_items']), 1)
            self.assertEqual(inbox['logical_items'][0]['assembly']['status'], 'complete')
            self.assertEqual(inbox['logical_items'][0]['presentation']['measurement']['source_kind'], 'video_replay')
            self.assertEqual(response.json['integration']['simulation_mode'], 'water-only')
            self.assertEqual(store.path.read_bytes(), before)

    def test_store_groups_beyond_old_twenty_packet_window_and_keeps_twenty_raw(self):
        temporary = Path(__file__).resolve().parents[3]/'outputs'/'test-tmp'
        temporary.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=temporary) as directory:
            store = ReportStore.initialize(directory)
            for group in range(6):
                for value in packets(base='web-'+f'{group:040x}'):
                    store.receive(json.dumps(value['report']).encode(), device_id=DEVICE, now=NOW)
            reader = ReportStore(directory, read_only=True)
            raw_before = reader.recent(DEVICE, now=NOW)
            view = recent_view(reader, DEVICE, now=NOW)
            self.assertEqual(view['items'], raw_before['items'])
            self.assertNotIn('logical_items', raw_before)
            self.assertEqual(len(view['items']), 20)
            self.assertEqual(len(view['logical_items']), 6)
            self.assertTrue(all(v['assembly']['status']=='complete' for v in view['logical_items']))


if __name__ == '__main__':
    unittest.main()
