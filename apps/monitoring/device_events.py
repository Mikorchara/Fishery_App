"""Register device report evidence in Monitoring without fabricating observations."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import re
import uuid

from .contracts import identifier
from .event_records import parse_time

CODE = 'DEVICE_REPORT_SIGNAL'
RULE_VERSION = 'device-report-presence-v1'
APPEARANCE = 'DEVICE_REPORT_APPEARANCE'
BEHAVIOR = 'DEVICE_REPORT_BEHAVIOR'
GAP = 'DEVICE_REPORT_GAP'
DEVICE_EVENT_CODES = (CODE, APPEARANCE, BEHAVIOR, GAP)
FRESH_SECONDS = 120
GAP_SECONDS = 180
ON_TIME_SECONDS = 60
CONTINUITY_SECONDS = 90
CONTINUITY_MIN_SECONDS = 30
CONTINUITY_WINDOWS = 3
PART_ID = re.compile(r'^web-[0-9a-f]{40}-[1-9][0-9]{0,2}$')


def stamp(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('DEVICE_REPORT_TIME_REQUIRED')
    return result.astimezone(timezone.utc)


def positive(report):
    return report.get('has_abnormality') is True or any(
        item.get('targets', 0) > 0 for item in report.get('abnormalities', []))


def payload_from_row(row):
    if not row:
        return None
    value = row['payload']
    return json.loads(value) if isinstance(value, str) else value


def cursor(db, device_id):
    row = db.execute("SELECT payload FROM current WHERE device_id=? AND channel='visual'", (device_id,)).fetchone()
    payload = payload_from_row(row)
    return payload.get('inbox_cursor', 0) if payload and payload.get('source_kind') == 'device_report' else 0


def peak_context(report):
    behavior = report.get('behavior')
    context = behavior.get('report_context') if isinstance(behavior, dict) else None
    return context if isinstance(context, dict) and context.get('aggregation_policy') == 'peak_frame_v1' else None


def legacy_report(report):
    behavior = report.get('behavior')
    return peak_context(report) is None and not (
        isinstance(behavior, dict) and behavior.get('aggregation_policy') == 'independent_video_results')


def positive_integer(value):
    return type(value) is int and value > 0


def valid_peak_window(report, context):
    return (not PART_ID.fullmatch(report['report_id'])
            and not report['report_text'].startswith('【结果分包')
            and positive_integer(report['window']['frames_processed'])
            and positive_integer(context.get('observed_detection_frames')))


def appearance_labels(report, context):
    if (context.get('abnormality_status') != 'observed'
            or context.get('abnormality_count_semantics') != 'detections_in_one_peak_frame'
            or not positive_integer(context.get('observed_abnormality_frames'))):
        return []
    return [item for item in report['abnormalities'] if item['targets'] > 0 and item['count'] == item['targets']]


def active_event(db, device, code):
    row = db.execute('''SELECT e.payload FROM alerts a JOIN events e ON e.id=a.event_id
        WHERE a.device_id=? AND a.channel='visual' AND a.code=?''', (device, code)).fetchone()
    event = payload_from_row(row)
    if event and event.get('source_kind') != 'device_report':
        raise ValueError('DEVICE_REPORT_EVENT_CONFLICT')
    return event


def write_event(db, event, *, active=True):
    db.execute('''INSERT INTO events VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload''',
        (event['id'], event['device_id'], 'visual', event['code'], json.dumps(event, ensure_ascii=False)))
    if active:
        db.execute('''INSERT INTO alerts VALUES(?,?,?,?) ON CONFLICT(device_id,channel,code)
            DO UPDATE SET event_id=excluded.event_id''', (event['device_id'], 'visual', event['code'], event['id']))
    else:
        db.execute("DELETE FROM alerts WHERE event_id=?", (event['id'],))


def new_event(device, code, title, version, *, occurred, received, report_id, event_id=None):
    return dict(id=event_id or uuid.uuid4().hex, device=device, device_id=device, channel='visual', code=code,
        type='设备视觉信号' if code != GAP else '设备报告状态', occurred_at=occurred.isoformat(),
        received_at=received.isoformat(), batch_id=report_id, attachments=[], source_kind='device_report',
        title=title, severity='warning', finding_severity='warning', status='pending', lifecycle_state='ACTIVE',
        state_reason=None, publication_status='PROTOTYPE', rule_version=version,
        rule_identity=dict(rule_id=code, version=version,
            scope=['device_report', 'visual', 'window_report', 'non_diagnostic'],
            publication_status='PROTOTYPE', assessment_policy_version=version))


def record_observation(event, report, observed, received, now):
    event.update(observation=dict(device_id=event['device_id'], channel='visual', batch_id=report['report_id'],
        source_kind='device_report', observed_at=observed.isoformat(), received_at=received.isoformat(),
        window_start=report['window']['start'], window_end=report['window']['end'],
        window_duration_s=report['window']['duration_s'], aggregation='window_report'),
        last_observed_at=observed.isoformat(), last_batch_id=report['report_id'], assessed_at=now.isoformat(),
        device_report=report)


def update_appearance(db, report, observed, received, now, *, labels=None):
    device = report['device_id']
    legacy = labels is None
    code = CODE if legacy else APPEARANCE
    title = '设备视觉异常报告（需核查）' if legacy else '外观异常待核查'
    version = RULE_VERSION if legacy else 'device-report-appearance-v1'
    event = active_event(db, device, code) or new_event(device, code, title, version,
        occurred=observed, received=received, report_id=report['report_id'])
    record_observation(event, report, observed, received, now)
    event['description'] = '设备模型报告的检测信号，需人工核查。'
    if legacy:
        # Preserve the legacy event payload and ACK identity.
        event['description'] = '设备模型报告的检测信号；不是疾病确诊，未执行设备操作。'
    else:
        event['device_report_event'] = dict(kind='appearance', labels=labels)
    write_event(db, event)
    return event['id']


def update_behavior(db, report, stream, *, observed, received, now, established_before):
    body = report['behavior']
    identity = body.get('report_id')
    at = parse_time(body.get('result_timestamp'))
    results = body.get('results')
    if (not isinstance(identity, str) or not 1 <= len(identity) <= 128 or not at
            or not 0 <= (now-at).total_seconds() <= FRESH_SECONDS or at > stamp(report['sent_at'])
            or body.get('aggregation_policy') != 'independent_video_results'
            or body.get('result_semantics') != 'snapshot_not_additive' or body.get('error')
            or not isinstance(results, list) or not 1 <= len(results) <= 100):
        return None
    if any(not isinstance(item, dict) or type(item.get('is_abnormal')) is not bool
            or not isinstance(item.get('video'), str) or not 1 <= len(item['video']) <= 500 for item in results):
        return None
    watermark = stream.get('last_behavior_result_at')
    if watermark and at <= stamp(watermark):
        return None
    stream['last_behavior_result_at'] = at.astimezone(timezone.utc).isoformat()
    baseline = stamp(stream['first_window_start'])
    # The board's flag compares prepared packets, which may never have reached us.
    # Unflagged versions need a source time after our first on-time observation.
    if body.get('new_result') is not True:
        if not established_before:
            return None
        baseline = stamp(stream['first_window_end'])
    if at <= baseline:
        return None
    videos = list(dict.fromkeys(item['video'] for item in results if item['is_abnormal']))
    if not videos:
        return None
    device = report['device_id']
    event_id = uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([BEHAVIOR, device, identity])).hex
    if db.execute('SELECT 1 FROM events WHERE id=?', (event_id,)).fetchone():
        return None
    event = new_event(device, BEHAVIOR, '行为模型异常待核查', 'device-report-behavior-v1',
        occurred=at, received=received, report_id=report['report_id'], event_id=event_id)
    record_observation(event, report, at, received, now)
    event['observation'].update(window_start=None, window_end=None, window_duration_s=None,
        aggregation='behavior_result_version')
    event.update(description='行为模型按视频标记异常，需人工核查。',
        device_report_event=dict(kind='behavior', result_id=identity,
            result_timestamp=at.astimezone(timezone.utc).isoformat(), abnormal_videos=videos))
    write_event(db, event)
    stream['last_behavior_event_id'] = event_id
    return event_id


def advance_stream(db, report, stream, observed, received, now):
    previous = stream.get('last_window_end')
    if previous and observed <= stamp(previous):
        return
    if not previous:
        stream.update(first_window_start=report['window']['start'], first_window_end=observed.isoformat())
    streak = stream.get('streak', 0)
    if not previous or not CONTINUITY_MIN_SECONDS <= (observed-stamp(previous)).total_seconds() <= CONTINUITY_SECONDS:
        streak = 0
    stream.update(last_window_end=observed.isoformat(), last_window_received_at=received.isoformat(),
        last_window_report_id=report['report_id'], streak=min(streak+1, CONTINUITY_WINDOWS))
    gap = active_event(db, report['device_id'], GAP)
    if gap:
        gap.update(lifecycle_state='RESOLVED', status='closed', state_reason='DEVICE_REPORT_UPDATES_RESUMED',
            resolved_at=max(received, stamp(gap['occurred_at'])).isoformat(), assessed_at=now.isoformat())
        gap['device_report_event']['resumed_window_end'] = observed.isoformat()
        write_event(db, gap, active=False)


def check_gap(db, device, *, now):
    identifier(device)
    now = stamp(now)
    row = db.execute("SELECT payload FROM current WHERE device_id=? AND channel='visual'", (device,)).fetchone()
    payload = payload_from_row(row)
    stream = payload.get('report_stream', {}) if payload and payload.get('source_kind') == 'device_report' else {}
    if stream.get('streak', 0) < CONTINUITY_WINDOWS:
        return None
    observed = stamp(stream['last_window_end'])
    if (now-observed).total_seconds() < GAP_SECONDS:
        return None
    active = active_event(db, device, GAP)
    if active:
        return active['id']
    if stream.get('gap_reported_through') == stream['last_window_end']:
        return None
    event = new_event(device, GAP, '设备报告更新中断', 'device-report-gap-v1',
        occurred=observed+timedelta(seconds=GAP_SECONDS), received=stamp(stream['last_window_received_at']),
        report_id=stream['last_window_report_id'])
    event.update(last_observed_at=observed.isoformat(), last_batch_id=stream['last_window_report_id'],
        assessed_at=now.isoformat(), description='连续上报后，设备报告未更新。',
        state_reason='DEVICE_REPORT_WINDOW_GAP', device_report_event=dict(kind='gap',
            last_window_end=observed.isoformat(), threshold_seconds=GAP_SECONDS))
    write_event(db, event)
    stream['gap_reported_through'] = stream['last_window_end']
    db.execute("UPDATE current SET payload=? WHERE device_id=? AND channel='visual'",
        (json.dumps(payload, ensure_ascii=False), device))
    return event['id']


def import_report(db, report, *, received_at, inbox_cursor, now):
    identifier(report['device_id'])
    identifier(report['report_id'])
    if type(inbox_cursor) is not int or inbox_cursor < 1:
        raise ValueError('DEVICE_REPORT_CURSOR_INVALID')
    now, received = stamp(now), stamp(received_at)
    observed = stamp(report['window']['end'])
    device = report['device_id']
    rows = db.execute('SELECT * FROM current WHERE device_id=?', (device,)).fetchall()
    if any(payload_from_row(row).get('source_kind') != 'device_report' for row in rows):
        raise ValueError('DEVICE_REPORT_DEVICE_CONFLICT')
    current = next((row for row in rows if row['channel'] == 'visual'), None)
    payload = payload_from_row(current)
    if payload and inbox_cursor <= payload.get('inbox_cursor', 0):
        return dict(status='duplicate', event_id=None)

    stream = payload.get('report_stream', {}) if payload else {}
    context = peak_context(report)
    if current:
        previous = stamp(current['observed_at'])
        same_peak = observed == previous and stream.get('last_window_end') == previous.isoformat()
        if observed < previous or same_peak:
            payload['inbox_cursor'] = inbox_cursor
            db.execute("UPDATE current SET payload=? WHERE device_id=? AND channel='visual'",
                (json.dumps(payload, ensure_ascii=False), device))
            return dict(status='out_of_order' if observed < previous else 'same_window', event_id=None)

    envelope = dict(source_kind='device_report', device_report=report, inbox_cursor=inbox_cursor)
    result = dict(status='no_signal', event_id=None)
    if not 0 <= (now-observed).total_seconds() <= FRESH_SECONDS:
        result['status'] = 'stale'
    elif legacy_report(report) and positive(report):
        result.update(status='accepted', event_id=update_appearance(db, report, observed, received, now))
    elif context is not None and valid_peak_window(report, context):
        on_time = stamp(report['sent_at']) <= received and 0 <= (received-observed).total_seconds() <= ON_TIME_SECONDS
        if on_time:
            established_before = bool(stream.get('last_window_end'))
            advance_stream(db, report, stream, observed, received, now)
            behavior_id = update_behavior(db, report, stream, observed=observed, received=received, now=now,
                established_before=established_before)
            if behavior_id:
                result.update(status='accepted', event_id=behavior_id)
            labels = appearance_labels(report, context)
            if labels:
                result.update(status='accepted', event_id=update_appearance(db, report, observed, received, now, labels=labels))
    if stream:
        envelope['report_stream'] = stream
    db.execute('''INSERT INTO current VALUES(?,?,?,?,?,?) ON CONFLICT(device_id,channel) DO UPDATE SET
        batch_id=excluded.batch_id,observed_at=excluded.observed_at,received_at=excluded.received_at,payload=excluded.payload''',
        (device, 'visual', report['report_id'], observed.isoformat(), received.isoformat(),
            json.dumps(envelope, ensure_ascii=False)))
    return result


def project(event, row, now):
    """Show current evidence separately from historical model signals."""
    result = deepcopy(event)
    now = stamp(now)
    payload = payload_from_row(row)
    report = payload.get('device_report') if payload and payload.get('source_kind') == 'device_report' else None
    code = event['code']
    observed = stamp(report['window']['end']) if report else None
    if code == BEHAVIOR:
        observed = stamp(event['device_report_event']['result_timestamp'])
    elif code == GAP:
        observed = stamp(event['device_report_event']['last_window_end'])
    age = (now-observed).total_seconds() if observed else None
    freshness = 'fresh' if age is not None and 0 <= age <= FRESH_SECONDS else 'stale' if age is not None and age > FRESH_SECONDS else 'unknown'
    context = peak_context(report) if report else None
    if code == GAP:
        active = True
        reason = 'DEVICE_REPORT_WINDOW_GAP'
    elif code == BEHAVIOR:
        active = bool(payload and payload.get('report_stream', {}).get('last_behavior_event_id') == event['id'])
        reason = None if active else 'DEVICE_REPORT_BEHAVIOR_SUPERSEDED'
    else:
        has_signal = bool(report and (
            (legacy_report(report) and positive(report)) if code == CODE else
            context is not None and report['report_id'] == event['last_batch_id'] and appearance_labels(report, context)))
        active = bool(has_signal and freshness == 'fresh' and observed >= stamp(event['last_observed_at']))
        reason = None if active else 'DEVICE_REPORT_STALE' if freshness == 'stale' else 'DEVICE_REPORT_CURRENT_SIGNAL_UNCONFIRMED'
    result.update(lifecycle_state='ACTIVE' if active else 'INDETERMINATE', status='pending',
        state_reason=reason, evaluated_at=now.isoformat(), current_data_quality=dict(
            quality='valid' if observed and code != GAP else 'missing', freshness=freshness, connectivity='unknown'))
    return result
