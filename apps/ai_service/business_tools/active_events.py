"""Read-only event summaries for server-bound Monitoring devices."""
from collections import Counter
from datetime import timedelta, timezone
import json
import re

from apps.ai_backend.model_gateway import ModelToolDefinition
from apps.monitoring.contracts import identifier, timestamp
from apps.monitoring.device_events import APPEARANCE, BEHAVIOR, CODE, GAP, GAP_SECONDS
from apps.monitoring.event_families import FAMILIES
from apps.monitoring.rules import VISUAL_RULES


ACTIVE_EVENTS = 'get_active_events'
ACTIVE_EVENTS_PROJECTION = 'management-active-events@3'
MAX_ACTIVE_EVENT_ITEMS = 10
MAX_ACTIVE_EVENT_CYCLES = 512  # Two repository snapshots of at most 256 records each.
MAX_ACTIVE_EVENT_RESULT_BYTES = 8192
ACTIVE_EVENTS_DEFINITION = ModelToolDefinition(
    ACTIVE_EVENTS,
    '问当前事件、异常或告警，且未限定为水质时，优先用本工具。只问当前水质读数或告警时用获准的当前水质工具。'
    '只读返回活动风险、待核实与待复核事件、观测范围及证据。板端报告仅在获授权时纳入。参数传 {}。',
    {'type': 'object', 'properties': {}, 'additionalProperties': False},
)
RESULT_INSTRUCTION = (
    "首句直接回答所问。只问证据时给该证据及其来源。问当前事件时先写活动风险，再写待核实与待复核。"
    "只有 ACTIVE 算活动风险。有一项时首句写具体名称，有多项时报数量再列全名称。"
    "INDETERMINATE 是当前状态待核实，NEEDS_REVIEW 是行为模型信号待复核。只有这两类时先写实际信号和状态，每项名称只写一次。\n"
    "空结果先读 observation_scope。有 ASSESSED 时，写「本次在〔有效观测的实际来源和通道〕范围内未查到匹配事件」。"
    "结论句带上该范围，只写一次。NO_DATA 或没有 ASSESSED 的空结果，说明缺少足够的有效观测，暂时无法核实。"
    "PARTIAL 表示覆盖不完整，MISSING 表示缺测，STALE 表示过期，UNUSABLE 表示无法用于当前判断。逐项保留会影响结论的限制。"
    "没有 ASSESSED 通道的来源只报告观测限制和明确返回的留存证据。即使其他来源有活动风险，也不要补写该来源「没有异常」或「未查到事件」。"
    "REPORT_ONLY 表示板端较新报告可查，外观与行为的完整观测范围仍未知。"
    "simulator 的 visual 是模拟视觉，只有 device_report 才是板端报告。只陈述本轮列出的来源。"
    "通道无匹配、缺测或过期，不能推断其他通道正常、风险消退或鱼群健康。"
    "问旧异常是否恢复而相关观测缺失或过期时，先说无法核实恢复，再说明所问来源的观测限制。\n"
    "同时问当前读数等其他事实时，继续获取获准且必要的来源，分别回答；历史只用于理解所指内容。"
    "分开注明模拟设备与设备报告，逐字引用相关来源的 device_id。"
    "事件查询时间和观测时间已是北京时间（UTC+08:00），直接引用年月日与钟点。"
    "分别标明各时间的含义。occurred_at 是本事件首次记录时间，last_observed_at 是最近观测，evaluated_at 是查询评估时间。"
    "用户未问内部字段时，省略字段名、状态码和规则码。"
    "行为 result_timestamp 是结果版本时间，按实际偏移标时区；abnormal_video_count 是被模型标为异常的视频数。"
    "所问时间缺失时说明未提供，行为结果未包含行为上报时间。"
    "报告中断只表示报告未更新，设备连接情况需另有证据。外观和行为信号用于人工核查，不能确诊疾病。结果截断时交代未展开条数。"
    "查询只读。确认、删除、结束事件和操作设备需另行处理。"
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
_EVENT_STATE_LABELS = {'ACTIVE': '活动', 'INDETERMINATE': '待核实', 'NEEDS_REVIEW': '待复核'}
_SCOPE_LIMITS = {'MISSING': '缺少观测', 'STALE': '观测已过期', 'UNUSABLE': '观测不可用于当前判断',
                 'PARTIAL': '观测覆盖不全', 'REPORT_ONLY': '有较新的报告，完整观测范围仍未知'}
_BOARD_UNVERIFIABLE_STATES = frozenset(('MISSING', 'STALE', 'UNUSABLE'))
_SEVERITIES = ('unknown', 'info', 'warning', 'critical')
_FRESHNESS = ('unknown', 'stale', 'fresh')
_BEIJING = timezone(timedelta(hours=8))
_BEHAVIOR_RESULT = r'(?:(?:当前|现在|这次)(?:的)?)?(?:板端)?行为(?:模型)?结果'
_BEHAVIOR_EVIDENCE_FIELDS = (
    ('video_count', re.compile(
        rf'(?:{_BEHAVIOR_RESULT}中)?(?:有)?(?:几个|多少(?:个)?)视频(?:被)?模型(?:标为|标记为)异常')),
    ('version_time', re.compile(
        rf'{_BEHAVIOR_RESULT}(?:的?(?:版本|生成)时间(?:是(?:什么时候|多少))?|(?:是)?什么时候生成(?:的)?)')),
    ('report_time', re.compile(
        rf'{_BEHAVIOR_RESULT}(?:的?上报时间(?:是(?:什么时候|多少))?|(?:是)?什么时候上报(?:的)?)')),
)
_FOLLOWUP_REPORT_TIME = re.compile(r'(?:能知道|能查到|可以知道|能否知道)?上报时间(?:吗)?')


def behavior_event_evidence_kind(question):
    """Match explicit questions about the returned behavior result, without other intents."""
    if not isinstance(question, str):
        return None
    fields = []
    for clause in (part.strip() for part in re.split(r'[，,。.;；?？!！]+', question.strip().rstrip('。.?？!！'))):
        field = next((name for name, pattern in _BEHAVIOR_EVIDENCE_FIELDS if pattern.fullmatch(clause)), None)
        if field is None and fields and _FOLLOWUP_REPORT_TIME.fullmatch(clause):
            field = 'report_time'
        if field is None or field in fields:
            return None
        fields.append(field)
    return tuple(fields)


def render_behavior_event_evidence(question, payload):
    """Render only the requested fields of the authenticated event result."""
    fields = behavior_event_evidence_kind(question)
    if fields is None:
        return None
    boards = [source['device_id'] for source in payload['sources'] if source['source_kind'] == 'device_report']
    if not boards:
        return '本轮查询未包含设备报告，暂时无法核实行为结果。'

    items = [item for item in payload['items'] if item['code'] == BEHAVIOR and item['device_id'] in boards]
    lines = []
    for item in items:
        evidence = item['evidence']
        details = [f"设备报告 {item['device_id']} 的行为模型结果待复核。"]
        if 'video_count' in fields:
            details.append(f"该版本有 {evidence['abnormal_video_count']} 个视频被模型标为异常。")
        if 'version_time' in fields or len(items) > 1:
            version = timestamp(evidence['result_timestamp']).astimezone(_BEIJING)
            details.append(f'行为结果版本时间为北京时间 {version:%Y-%m-%d %H:%M:%S}。')
        if item['freshness'] == 'stale':
            details.append('该版本已过期，当前状态暂时无法核实。')
        elif item['freshness'] == 'unknown':
            details.append('该版本的新鲜度未知，当前状态暂时无法核实。')
        lines.append(''.join(details))
    if not items:
        source = '、'.join(boards)
        lines.append(f'本轮未取得设备报告 {source} 中可核实的行为模型结果。')
    if payload['omitted_count']:
        lines.append(f"本轮事件查询另有 {payload['omitted_count']} 条记录未展开。")
    if 'report_time' in fields:
        lines.append('本轮结果未提供行为上报时间。')
    return '\n'.join(lines)


def _observation_state(source_kind, observation):
    if observation['observed_at'] is None:
        return 'MISSING'
    if observation['freshness'] == 'stale':
        return 'STALE'
    if observation['freshness'] != 'fresh':
        return 'UNUSABLE'
    if source_kind == 'device_report':
        return 'REPORT_ONLY'
    if observation['connectivity'] != 'online':
        return 'UNUSABLE'
    return {'valid': 'ASSESSED', 'partial': 'PARTIAL'}.get(observation['quality'], 'UNUSABLE')


def _observation_scope(sources):
    return [dict(source_kind=source['source_kind'], device_id=source['device_id'],
                 channel=observation['channel'], state=_observation_state(source['source_kind'], observation),
                 observed_at=observation['observed_at'])
            for source in sources for observation in source['observations']]


def _observation_time(value):
    observed = timestamp(value).astimezone(_BEIJING)
    return f'（北京时间 {observed:%Y-%m-%d %H:%M:%S}）'


def _event_timestamp(value):
    return timestamp(value).astimezone(_BEIJING).isoformat() if value is not None else None


def render_empty_event_scope(payload):
    """Render a validated, empty event receipt for a standalone event question."""
    if payload['status'] not in ('NO_MATCH', 'NO_DATA'):
        return None
    assessed, limits = [], []
    for scope in payload['observation_scope']:
        board = scope['source_kind'] == 'device_report'
        water = scope['channel'] == 'water'
        label = '板端视觉' if board else '模拟水质' if water else '模拟视觉'
        label += f"（{scope['device_id']}）"
        state = scope['state']
        if state == 'ASSESSED':
            assessed.append(label + _observation_time(scope['observed_at']))
            continue
        if state == 'REPORT_ONLY':
            observed = _observation_time(scope['observed_at'])
            limits.append(f'{label}有较新的报告{observed}，当前外观和行为的完整观测范围仍未知。')
            continue
        reason = {'PARTIAL': '观测覆盖不完整', 'MISSING': '缺少观测',
                  'STALE': '最新报告已过期' if board else '观测已过期',
                  'UNUSABLE': '观测无法用于当前判断'}[state]
        if state == 'STALE':
            reason += _observation_time(scope['observed_at'])
        subject = '外观和行为异常' if board else '水质事件' if water else '视觉异常'
        coverage = '全面' if state == 'PARTIAL' else ''
        limits.append(f'{label}{reason}，暂时无法{coverage}核实{subject}。')
    if assessed:
        verdict = f'本次在{"、".join(assessed)}的有效观测范围内未查到匹配事件。'
    elif payload['status'] == 'NO_DATA':
        verdict = '本次缺少观测，暂时无法核实当前事件。'
    else:
        verdict = '本次缺少足够的有效观测，暂时无法核实当前事件。'
    return '\n\n'.join((verdict, *limits))


def render_positive_event_scope(payload, *, explain_board_limit=False):
    """Render findings and observation limits from a validated positive event receipt."""
    lines = []
    for source in payload['sources']:
        board = source['source_kind'] == 'device_report'
        device_id = source['device_id']
        label = f"{'设备报告' if board else '模拟设备'} {device_id}"
        items = [f"{item['title']}（{_EVENT_STATE_LABELS[item['state']]}）"
                 for item in payload['items'] if item['device_id'] == device_id]
        if items:
            lines.append(f'在{label}的记录中查到{"、".join(items)}。')
        for scope in payload['observation_scope']:
            state = scope['state']
            if scope['device_id'] == device_id and state in _SCOPE_LIMITS:
                channel = '视觉' if scope['channel'] == 'visual' else '水质'
                limit = _SCOPE_LIMITS[state]
                if explain_board_limit and board and state in _BOARD_UNVERIFIABLE_STATES:
                    limit += '，暂时无法核实外观和行为异常'
                lines.append(f'{label}的{channel}{limit}。')
    if payload['omitted_count']:
        lines.append(f"另有 {payload['omitted_count']} 条匹配事件未展开。")
    return '\n'.join(lines)


def render_positive_event_scope_if_board_limited(payload):
    """Protect the board coverage boundary when other findings can be reported."""
    if payload['status'] == 'OK' and any(
        row['source_kind'] == 'device_report' and row['state'] in _BOARD_UNVERIFIABLE_STATES
        for row in payload['observation_scope']
    ):
        return render_positive_event_scope(payload, explain_board_limit=True)
    return None


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
        return dict(kind='behavior_version', result_timestamp=_event_timestamp(raw['result_timestamp']),
            abnormal_video_count=len(raw['abnormal_videos']))
    if code == GAP:
        return dict(kind='report_gap', last_window_end=_event_timestamp(raw['last_window_end']),
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
        severity=event.get('severity', 'unknown'), occurred_at=_event_timestamp(event['occurred_at']),
        last_observed_at=_event_timestamp(event.get('last_observed_at')), freshness=quality.get('freshness', 'unknown'),
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
        observations = [dict(row, observed_at=_event_timestamp(row['observed_at'])) for row in source['observations']]
        sources.append({**source, 'observations': observations, **{key: counts[state] for state, key in _STATE_COUNTS.items()}})
        items.extend(current)
    items.sort(key=lambda item: (_STATE_PRIORITY[item['state']],
        _SEVERITIES.index(item['severity']), timestamp(item['last_observed_at'] or item['occurred_at'])), reverse=True)
    observed = any(o['observed_at'] for source in sources for o in source['observations'])
    payload = dict(projection_version=ACTIVE_EVENTS_PROJECTION,
        status='OK' if items else 'NO_MATCH' if observed else 'NO_DATA',
        query_completed=True, evaluated_at=_event_timestamp(now.isoformat()), sources=sources,
        observation_scope=_observation_scope(sources),
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
                'evaluated_at', 'sources', 'observation_scope', 'items', 'total_count', 'omitted_count'}
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
                        or (expected_kind == 'device_report' and (item['connectivity'] != 'unknown'
                            or (item['observed_at'] is not None and item['quality'] != 'unknown')))
                        or (item['observed_at'] is None and
                            (item['quality'] != 'missing' or item['freshness'] != 'unknown'))):
                    return None
            observations[source['device_id']] = (expected_kind, channels)
            source_counts[source['device_id']] = {state: source[key] for state, key in _STATE_COUNTS.items()}
            if sum(source_counts[source['device_id']].values()) > MAX_ACTIVE_EVENT_CYCLES//2:
                return None
        observed = any(item['observed_at'] for source in sources for item in source['observations'])
        status = 'OK' if payload['total_count'] else 'NO_MATCH' if observed else 'NO_DATA'
        if (payload['status'] != status or payload['observation_scope'] != _observation_scope(sources)
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
