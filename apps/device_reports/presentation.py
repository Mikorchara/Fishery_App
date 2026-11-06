"""Read-only projection of device packets; never changes ingestion or event evidence.

Multipart hashes prove transport assembly, not inference accuracy. Each task keeps
its own source time; reported lengths and behavior flags are not business rules.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re

MAX_SCAN_PACKETS = 200
MAX_LOGICAL_REPORTS = 20
MAX_PARTS = 32
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_TASK_ITEMS = 100
_PART_ID = re.compile(r'^(web-[0-9a-f]{40})-([1-9][0-9]{0,2})$')
_HEADER = re.compile(r'^【结果分包 ([1-9][0-9]{0,2})/([1-9][0-9]{0,2})；SHA256=([0-9a-f]{64})】\r?\n')
_ORIGINAL_MARKER = '【完整原始 JSON】'
_COUNT_KEYS = ('fish_detected', 'fish_measured', 'fish_uncertain', 'fish_computed',
               'fish_with_pixel_length', 'fish_geometry_failed', 'fish_skipped')


def _text(value, maximum=500):
    return value[:maximum] if isinstance(value, str) else None


def _number(value):
    if type(value) not in (int, float) or value < 0:
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def _count(value):
    return value if type(value) is int and _number(value) is not None else None


def _channel_meta(packet, body=None):
    result = dict(source_kind=_text(packet.get('source_kind'), 80),
                  captured_at=_text(packet.get('capture_timestamp'), 100))
    if isinstance(body, dict):
        for key, value in _channel_meta(body).items():
            if value is not None:
                result[key] = value
    return result


def _measurement(packet, *, pending=False):
    result = dict(status='pending' if pending else 'missing', source_kind=None,
                  captured_at=None, counts={key: None for key in _COUNT_KEYS},
                  calibration_status=None, measurement_note=None, fishes=[],
                  total_fishes=0, display_truncated=False)
    if pending or packet is None:
        return result
    result['status'] = 'unrecognized'
    if not isinstance(packet, dict):
        return result
    body = packet.get('measurement', packet)
    result.update(_channel_meta(packet, body))
    if not isinstance(body, dict) or not ('fishes' in body or any(key in body for key in _COUNT_KEYS)):
        return result
    result.update(status='available', counts={key: _count(body.get(key)) for key in _COUNT_KEYS},
                  calibration_status=_text(body.get('calibration_status'), 120),
                  measurement_note=_text(body.get('measurement_note'), 1500))
    fishes = body.get('fishes')
    if not isinstance(fishes, list):
        return result
    result['total_fishes'] = len(fishes)
    result['display_truncated'] = len(fishes) > MAX_TASK_ITEMS
    for fish in fishes[:MAX_TASK_ITEMS]:
        if not isinstance(fish, dict):
            continue
        identity = fish.get('display_id', fish.get('fish_id'))
        if type(identity) is int:
            identity = str(identity)
        result['fishes'].append(dict(id=_text(identity, 80), status=_text(fish.get('status'), 120),
            status_text=_text(fish.get('status_text'), 160), length_px=_number(fish.get('length_px')),
            length_mm=_number(fish.get('length_mm')), physical_length_mm=_number(fish.get('physical_length_mm')),
            quality_warnings=[text for value in fish.get('quality_warnings', [])[:20]
                              if (text := _text(value, 120)) is not None]
                            if isinstance(fish.get('quality_warnings'), list) else [],
            association_status=_text(fish.get('association_status'), 120)))
    return result


def _behavior(packet, *, pending=False):
    result = dict(status='pending' if pending else 'missing', source_kind=None, captured_at=None,
                  model=None, anomalous_reported=None, clip_count=0, anomalous_clips=0,
                  unknown_clips=0, clips=[], display_truncated=False)
    if pending or packet is None:
        return result
    result['status'] = 'unrecognized'
    if not isinstance(packet, dict):
        return result
    body = packet.get('behavior', packet)
    result.update(_channel_meta(packet, body))
    if not isinstance(body, dict) or not isinstance(body.get('clips'), list):
        return result
    clips = body['clips']
    result.update(status='available', model=_text(body.get('source'), 120),
        anomalous_reported=_count(body.get('anomalous')), clip_count=len(clips),
        anomalous_clips=sum(isinstance(c, dict) and c.get('anomaly') is True for c in clips),
        unknown_clips=sum(not isinstance(c, dict) or type(c.get('anomaly')) is not bool for c in clips),
        display_truncated=len(clips) > MAX_TASK_ITEMS)
    for clip in clips[:MAX_TASK_ITEMS]:
        if not isinstance(clip, dict):
            continue
        result['clips'].append(dict(start_s=_number(clip.get('start_s')), end_s=_number(clip.get('end_s')),
                                   score=_number(clip.get('score')),
                                   anomaly=clip.get('anomaly') if type(clip.get('anomaly')) is bool else None))
    return result


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


def _presentation(report, issues, *, pending=False):
    detection = dict(status='available', **deepcopy(report['detection']),
                     frames_processed=report['window']['frames_processed'],
                     window=deepcopy(report['window']), abnormalities=deepcopy(report['abnormalities']))
    measurement, behavior = report.get('measurement'), report.get('behavior')
    document = report.get('report_text', '')
    if not pending and _ORIGINAL_MARKER in document:
        try:
            original = json.loads(document.split(_ORIGINAL_MARKER, 1)[1], object_pairs_hook=_object_pairs,
                                  parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
            if not isinstance(original, dict) or original.get('device_id') != report['device_id']:
                raise ValueError('different original device')
            inputs = original.get('inputs')
            if not isinstance(inputs, dict):
                raise ValueError('unrecognized inputs')
            measurement, behavior = inputs.get('measurement'), inputs.get('behavior')
        except (ValueError, TypeError, RecursionError):
            issues.append('ORIGINAL_JSON_UNRECOGNIZED')
    return dict(detection=detection, measurement=_measurement(measurement, pending=pending),
                behavior=_behavior(behavior, pending=pending))


def _context(report):
    return {key: value for key, value in report.items() if key not in ('report_id', 'report_text', 'sent_at')}


def _project_group(items, base_id, multipart):
    first = items[0]
    report = deepcopy(first['report'])
    issues, fragments, expected, digest = [], {}, None, None
    raw_parts = [dict(report_id=item['report']['report_id'], report_text=item['report']['report_text'],
                      received_at=item['received_at']) for item in items]
    warnings = list(dict.fromkeys(warning for item in items for warning in item.get('warnings', [])))
    status = 'single'
    if multipart:
        report['report_id'] = base_id
        for item in items:
            value = item['report']
            header = _HEADER.match(value['report_text'])
            identity = _PART_ID.fullmatch(value['report_id'])
            if not header or not identity or int(header[1]) != int(identity[2]):
                issues.append('PART_HEADER_INVALID')
                continue
            index, total = int(header[1]), int(header[2])
            if total > MAX_PARTS or index > total:
                issues.append('PART_LIMIT_OR_INDEX_INVALID')
                continue
            if expected is None:
                expected, digest = total, header[3]
            if expected != total or digest != header[3] or _context(value) != _context(report):
                issues.append('PART_CONTEXT_CONFLICT')
            fragment = value['report_text'][header.end():]
            if index in fragments and fragments[index] != fragment:
                issues.append('PART_CONTENT_CONFLICT')
            fragments[index] = fragment
        status = 'invalid' if issues else 'incomplete'
        document = ''
        if not issues and expected is not None and set(fragments) == set(range(1, expected + 1)):
            document = ''.join(fragments[index] for index in range(1, expected + 1))
            encoded = document.encode('utf-8')
            if len(encoded) > MAX_DOCUMENT_BYTES:
                issues.append('ASSEMBLED_DOCUMENT_TOO_LARGE')
            elif hashlib.sha256(encoded).hexdigest() != digest:
                issues.append('ASSEMBLED_HASH_MISMATCH')
            else:
                status = 'complete'
            if issues:
                status = 'invalid'
        report['report_text'] = document if status == 'complete' else ''
    elif report['report_text'].startswith('【结果分包'):
        issues.append('PART_HEADER_INVALID')
        status = 'invalid'
        report['report_text'] = ''
    assembly = dict(status=status, received_parts=len(fragments) if multipart else 1,
                    total_parts=expected if expected is not None else (None if multipart else 1), issue_codes=issues)
    projection = _presentation(report, issues, pending=status in ('incomplete', 'invalid'))
    return dict(report=report, received_at=max(item['received_at'] for item in items),
                freshness=first['freshness'], warnings=warnings, assembly=assembly,
                presentation=projection, raw_parts=raw_parts)


def project_reports(items):
    """Newest-first bounded packets -> at most twenty logical, read-only reports."""
    groups = {}
    for item in items[:MAX_SCAN_PACKETS]:
        report = item['report']
        match = _PART_ID.fullmatch(report['report_id'])
        multipart = match is not None
        base = match[1] if match else report['report_id']
        key = (report['device_id'], base, multipart)
        groups.setdefault(key, []).append(item)
    return [_project_group(group, key[1], key[2]) for key, group in list(groups.items())[:MAX_LOGICAL_REPORTS]]


def recent_view(store, device_id, *, now):
    """Web-only bounded read adapter; shared inbox and event/QQ readers stay unchanged."""
    if not store.read_only:
        raise ValueError('DEVICE_REPORT_READ_ONLY_BINDING_REQUIRED')
    with store.connection() as db:
        rows = db.execute('SELECT received_at,payload,warnings FROM reports WHERE device_id=? '
            'ORDER BY observed_at DESC,received_at DESC,report_id DESC LIMIT ?',
            (device_id, MAX_SCAN_PACKETS)).fetchall()
    items = []
    for received_at, payload, warnings in rows:
        report = json.loads(payload)
        observed = datetime.fromisoformat(report['window']['end'].replace('Z', '+00:00'))
        age = (now-observed).total_seconds()
        items.append(dict(report=report, received_at=received_at, warnings=json.loads(warnings),
            freshness='fresh' if 0 <= age <= 120 else 'stale' if age > 120 else 'unknown'))
    return dict(device_id=device_id, source_kind='device_report', items=items[:20],
                logical_items=project_reports(items), packet_scan_limit=MAX_SCAN_PACKETS,
                packet_scan_limited=len(rows) == MAX_SCAN_PACKETS,
                semantics='RAW_REPORT_ONLY_NO_EVENT_RECOVERY', water_source='SIMULATOR',
                connectivity='unknown', task_coverage='unknown')
