"""Read-only event summaries for server-bound Monitoring devices."""
from collections import Counter
import json

from apps.ai_backend.model_gateway import ModelToolDefinition
from apps.monitoring.contracts import identifier, timestamp
from apps.monitoring.device_events import APPEARANCE, BEHAVIOR, CODE, GAP, GAP_SECONDS
from apps.monitoring.event_families import FAMILIES
from apps.monitoring.rules import VISUAL_RULES


ACTIVE_EVENTS = 'get_active_events'
ACTIVE_EVENTS_PROJECTION = 'management-active-events@1'
MAX_ACTIVE_EVENT_ITEMS = 10
MAX_ACTIVE_EVENT_CYCLES = 512  # Two repository snapshots of at most 256 records each.
MAX_ACTIVE_EVENT_RESULT_BYTES = 8192
ACTIVE_EVENTS_DEFINITION = ModelToolDefinition(
    ACTIVE_EVENTS,
    '只读查询本轮绑定设备的活动事件、待核实事件和待复核的行为结果。若已授权设备报告，也可返回该设备的外观异常、行为异常和报告中断。'
    '只使用程序返回的来源、事件状态及时间。NO_MATCH 表示已查询范围内没有符合条件的事件，NO_DATA 表示该范围没有观测。'
    '两者都不能证明鱼群健康或无风险。行为文件可能过期，报告中断不证明设备离线。按 evidence 和观察时间如实说明。'
    '设备由服务端固定，参数必须为 {}。',
    {'type': 'object', 'properties': {}, 'additionalProperties': False},
)

_WATER_TITLES = {code: value[1] for code, value in FAMILIES.items()}
_VISUAL_TITLES = {code: value[1] for code, value in VISUAL_RULES.items()}
_QUALITY_TITLES = {
    'SENSOR_INVALID': '观测数据无效', 'SENSOR_PARTIAL': '观测覆盖不完整',
    'SENSOR_MISSING': '缺少可用观测', 'SENSOR_STALE': '观测已过期',
    'DEVICE_OFFLINE': '监测上报中断',
}
_BOARD_TITLES = {
    CODE: '设备视觉异常报告（旧版）', APPEARANCE: '外观异常待核查',
    BEHAVIOR: '行为模型异常待核查', GAP: '设备报告更新中断',
}
_APPEARANCE_LABELS = {
    'ascites': '腹水', 'head_ulceration': '头部溃疡', 'body_ulceration': '体表溃疡',
}
_STATE_COUNTS = {'ACTIVE': 'active_count', 'NEEDS_REVIEW': 'review_count', 'INDETERMINATE': 'uncertain_count'}
_STATE_PRIORITY = {'ACTIVE': 2, 'NEEDS_REVIEW': 1, 'INDETERMINATE': 0}
_SEVERITIES = ('unknown', 'info', 'warning', 'critical')
_FRESHNESS = ('unknown', 'stale', 'fresh')


def _title(source, channel, code):
    if source == 'device_report':
        return _BOARD_TITLES.get(code)
    titles = _WATER_TITLES if channel == 'water' else _VISUAL_TITLES
    return titles.get(code) or _QUALITY_TITLES.get(code)


def _evidence(event, code):
    raw = event.get('device_report_event') or {}
    if code == APPEARANCE:
        labels = []
        for item in raw['labels']:
            label = _APPEARANCE_LABELS.get(item['label'])
            if label is not None:
                labels.append(dict(label=label, targets=item['targets']))
        return dict(kind='appearance_peak', labels=labels, other_label_count=len(raw['labels'])-len(labels))
    if code == BEHAVIOR:
        return dict(kind='behavior_version', result_timestamp=raw['result_timestamp'],
            abnormal_video_count=len(raw['abnormal_videos']))
    if code == GAP:
        return dict(kind='report_gap', last_window_end=raw['last_window_end'],
            threshold_seconds=raw['threshold_seconds'])
    return None


def _item(event, source):
    if (event.get('status') == 'closed' or event.get('superseded_by')
            or event.get('manual_end', {}).get('active')):
        return None
    lifecycle = event.get('lifecycle_state')
    code, channel = event['code'], event['channel']
    if lifecycle not in ('ACTIVE', 'INDETERMINATE'):
        return None
    title = _title(source['source_kind'], channel, code)
    if title is None:
        # Legacy records without a supported rule remain visible in the event
        # page. Never pass their free-form fields through a model Tool.
        return None
    if code == BEHAVIOR and lifecycle != 'ACTIVE':
        return None  # Earlier behavior files are available in report history.
    quality = event.get('current_data_quality') or {}
    return dict(source_kind=source['source_kind'], device_id=source['device_id'],
        channel=channel, code=code, title=title, state='NEEDS_REVIEW' if code == BEHAVIOR else lifecycle,
        severity=event.get('severity', 'unknown'), occurred_at=event['occurred_at'],
        last_observed_at=event.get('last_observed_at'), freshness=quality.get('freshness', 'unknown'),
        evidence=_evidence(event, code))


def active_events_payload(monitoring, device_id, *, board_device_id=None):
    """Project only finite source metadata and approved event fields to the model."""
    now, scopes = monitoring.active_event_snapshot(device_id, board_device_id=board_device_id)
    expected = [('simulator', device_id)]
    if board_device_id is not None:
        expected.append(('device_report', board_device_id))
    if [(source['source_kind'], source['device_id']) for source, _ in scopes] != expected:
        raise ValueError('ACTIVE_EVENT_SCOPE_MISMATCH')
    sources, items = [], []
    for source, events in scopes:
        current = [item for event in events if (item := _item(event, source)) is not None]
        counts = Counter(item['state'] for item in current)
        sources.append({**source, **{key: counts[state] for state, key in _STATE_COUNTS.items()}})
        items.extend(current)
    items.sort(key=lambda item: (_STATE_PRIORITY[item['state']],
        _SEVERITIES.index(item['severity']), timestamp(item['last_observed_at'] or item['occurred_at'])), reverse=True)
    observed = any(o['observed_at'] for source in sources for o in source['observations'])
    payload = dict(projection_version=ACTIVE_EVENTS_PROJECTION,
        status='OK' if items else 'NO_MATCH' if observed else 'NO_DATA',
        query_completed=True, evaluated_at=now.isoformat(), sources=sources,
        items=items[:MAX_ACTIVE_EVENT_ITEMS], total_count=len(items),
        omitted_count=max(0, len(items)-MAX_ACTIVE_EVENT_ITEMS))
    if result_metadata(payload) is None:
        raise ValueError('ACTIVE_EVENT_RESULT_INVALID')
    return payload


def _count(value, maximum=MAX_ACTIVE_EVENT_CYCLES):
    return type(value) is int and 0 <= value <= maximum


def _time_not_future(value, evaluated):
    return value is None or timestamp(value) <= evaluated


def _valid_evidence(code, value, evaluated):
    if code == APPEARANCE:
        return (type(value) is dict and set(value) == {'kind', 'labels', 'other_label_count'}
                and value['kind'] == 'appearance_peak' and type(value['labels']) is list
                and _count(value['other_label_count'], 32)
                and 1 <= len(value['labels'])+value['other_label_count'] <= 32
                and all(type(label) is dict and set(label) == {'label', 'targets'}
                    and label['label'] in _APPEARANCE_LABELS.values()
                    and _count(label['targets'], 100_000) and label['targets'] > 0 for label in value['labels'])
                and len({label['label'] for label in value['labels']}) == len(value['labels']))
    if code == BEHAVIOR:
        return (type(value) is dict and set(value) == {'kind', 'result_timestamp', 'abnormal_video_count'}
                and value['kind'] == 'behavior_version' and timestamp(value['result_timestamp']) <= evaluated
                and _count(value['abnormal_video_count'], 100) and value['abnormal_video_count'] > 0)
    if code == GAP:
        return (type(value) is dict and set(value) == {'kind', 'last_window_end', 'threshold_seconds'}
                and value['kind'] == 'report_gap' and timestamp(value['last_window_end']) <= evaluated
                and type(value['threshold_seconds']) is int and value['threshold_seconds'] == GAP_SECONDS)
    return value is None


def result_metadata(payload):
    """Validate the versioned result and return bounded source receipt metadata."""
    try:
        if (type(payload) is not dict or set(payload) != {'projection_version', 'status', 'query_completed',
                'evaluated_at', 'sources', 'items', 'total_count', 'omitted_count'}
                or payload['projection_version'] != ACTIVE_EVENTS_PROJECTION
                or payload['query_completed'] is not True or not _count(payload['total_count'])
                or not _count(payload['omitted_count'])
                or type(payload['sources']) is not list or not 1 <= len(payload['sources']) <= 2
                or type(payload['items']) is not list
                or len(payload['items']) != min(payload['total_count'], MAX_ACTIVE_EVENT_ITEMS)
                or len(payload['items']) + payload['omitted_count'] != payload['total_count']
                or len(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8'))
                   > MAX_ACTIVE_EVENT_RESULT_BYTES):
            return None
        evaluated = timestamp(payload['evaluated_at'])
        observations, source_counts = {}, {}
        sources = payload['sources']
        for index, source in enumerate(sources):
            if type(source) is not dict or set(source) != {
                    'source_kind', 'device_id', 'observations', *_STATE_COUNTS.values()}:
                return None
            identifier(source['device_id'])
            expected_kind = 'simulator' if index == 0 else 'device_report'
            channels = ('water', 'visual') if index == 0 else ('visual',)
            if (source['source_kind'] != expected_kind or source['device_id'] in observations
                    or type(source['observations']) is not list or len(source['observations']) != len(channels)
                    or not all(_count(source[key], MAX_ACTIVE_EVENT_CYCLES//2) for key in _STATE_COUNTS.values())):
                return None
            for channel, item in zip(channels, source['observations']):
                if (type(item) is not dict or set(item) != {'channel', 'observed_at', 'quality', 'freshness', 'connectivity'}
                        or item['channel'] != channel or not _time_not_future(item['observed_at'], evaluated)
                        or item['quality'] not in ('valid', 'partial', 'invalid', 'missing', 'unknown')
                        or item['freshness'] not in _FRESHNESS
                        or item['connectivity'] not in ('online', 'offline', 'never_received', 'unknown')
                        or (expected_kind == 'device_report' and item['connectivity'] != 'unknown')
                        or (item['observed_at'] is None and
                            (item['quality'] != 'missing' or item['freshness'] != 'unknown'))):
                    return None
            observations[source['device_id']] = (expected_kind, channels)
            source_counts[source['device_id']] = {state: source[key] for state, key in _STATE_COUNTS.items()}
            if sum(source_counts[source['device_id']].values()) > MAX_ACTIVE_EVENT_CYCLES//2:
                return None
        observed = any(item['observed_at'] for source in sources for item in source['observations'])
        status = 'OK' if payload['total_count'] else 'NO_MATCH' if observed else 'NO_DATA'
        if (payload['status'] != status
                or sum(sum(counts.values()) for counts in source_counts.values()) != payload['total_count']):
            return None
        for item in payload['items']:
            if type(item) is not dict or set(item) != {'source_kind', 'device_id', 'channel', 'code', 'title', 'state',
                    'severity', 'occurred_at', 'last_observed_at', 'freshness', 'evidence'}:
                return None
            kind, channels = observations[item['device_id']]
            title = _title(kind, item['channel'], item['code'])
            counts = source_counts[item['device_id']]
            if (item['source_kind'] != kind or item['channel'] not in channels or title is None or item['title'] != title
                    or counts[item['state']] < 1 or (item['state'] == 'NEEDS_REVIEW') != (item['code'] == BEHAVIOR)
                    or item['severity'] not in _SEVERITIES or item['freshness'] not in _FRESHNESS
                    or timestamp(item['occurred_at']) > evaluated or not _time_not_future(item['last_observed_at'], evaluated)
                    or not _valid_evidence(item['code'], item['evidence'], evaluated)):
                return None
            counts[item['state']] -= 1
        return dict(active_events_query_completed=True, active_events_count=payload['total_count'],
            active_events_source_count=len(sources), active_events_omitted_count=payload['omitted_count'],
            active_events_status='NO_ACTIVE_EVENTS' if status == 'NO_MATCH' else status,
            evaluated_at=evaluated.isoformat())
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError):
        return None
