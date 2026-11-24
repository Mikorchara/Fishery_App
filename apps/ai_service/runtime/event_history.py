"""Evidence-bound reply for a current-event query and an explicit historical mean request."""

import re

from ..business_tools.active_events import ACTIVE_EVENTS, render_empty_event_scope
from ..business_tools.water_quality_history import WATER_QUALITY_HISTORY
from .event_notice import requires_active_events
from .history_summary import HistorySummary, render_history_summary


_OXYGEN = 'dissolved_oxygen_mg_l'
_EVENT = re.compile(r'(?:请)?(?:先)?(?:查(?:一下)?|查询|查看|看看)(?:当前|现在|目前)(?:的)?(?:活动)?事件')
_MEAN = r'(?:可靠窗口(?:的)?)?总体均值'
_HISTORY = re.compile(
    r'(?:(?:请)?(?:再|同时|顺便)?(?:查(?:一下)?|查询|查看|看看)|以及)?\s*'
    r'(?:过去|最近|近)\s*(?:(?P<minutes>10|30|60)\s*分钟|(?P<hours>半|一|1)\s*小时)'
    rf'\s*(?:的)?(?:溶解氧|溶氧)(?:的)?(?P<mean>{_MEAN})?'
)
_HISTORY_FOLLOWUP = re.compile(rf'(?:历史部分)?(?:请)?(?:给出|说明)(?:(?:时段|时间范围)和)?{_MEAN}')
_SEPARATOR = re.compile(r'[,，。！!？?；;]')
_EVENT_STATES = {'ACTIVE': '活动', 'INDETERMINATE': '待核实', 'NEEDS_REVIEW': '待复核'}
_SCOPE_LIMITS = {'MISSING': '缺少观测', 'STALE': '观测已过期', 'UNUSABLE': '观测不可用于当前判断',
    'PARTIAL': '观测覆盖不全', 'REPORT_ONLY': '有较新的报告，完整观测范围仍未知'}


def event_history_query(question):
    """Match only a current-events request plus a named historical oxygen mean."""
    if not isinstance(question, str):
        return None
    clauses = [part.strip() for part in _SEPARATOR.split(question.strip().rstrip('。！!？?'))]
    if len(clauses) not in (2, 3, 4):
        return None
    event, history, *tail = clauses
    if not (_EVENT.fullmatch(event) or requires_active_events(event)):
        return None
    match = _HISTORY.fullmatch(history)
    if match is None:
        return None
    if tail and tail[0] in ('请分别说明结论', '分别说明结论'):
        tail.pop(0)
    if tail:
        if len(tail) != 1 or match['mean'] or not _HISTORY_FOLLOWUP.fullmatch(tail[0]):
            return None
    elif not match['mean']:
        return None
    minutes = int(match['minutes']) if match['minutes'] else 30 if match['hours'] == '半' else 60
    return HistorySummary(minutes, _OXYGEN, None)


def event_history_for_turn(request, policy):
    """Select only a standalone turn that is authorized for both evidence sources."""
    if request.history or not policy.allows(ACTIVE_EVENTS) or not policy.allows(WATER_QUALITY_HISTORY):
        return None
    return event_history_query(request.question)


def event_history_instruction(summary):
    return (f'本轮分别查当前事件和最近 {summary.minutes} 分钟的历史溶解氧。'
            f'先用 {ACTIVE_EVENTS}，参数为空对象，再用 {WATER_QUALITY_HISTORY}，'
            f'参数 lookback_minutes={summary.minutes}，metrics=["{_OXYGEN}"]。'
            '各报告本轮范围和证据。历史工具未返回可靠窗口总体均值时，说明缺项，勿用代表窗口或首末值估算。')


def _positive_events(payload):
    lines = []
    for source in payload['sources']:
        board = source['source_kind'] == 'device_report'
        device_id = source['device_id']
        label = f"{'设备报告' if board else '模拟设备'} {device_id}"
        items = [f"{item['title']}（{_EVENT_STATES[item['state']]}）"
                 for item in payload['items'] if item['device_id'] == device_id]
        if items:
            lines.append(f'在{label}的记录中查到{"、".join(items)}。')
        for scope in payload['observation_scope']:
            if scope['device_id'] == device_id and scope['state'] in _SCOPE_LIMITS:
                channel = '视觉' if scope['channel'] == 'visual' else '水质'
                lines.append(f"{label}的{channel}{_SCOPE_LIMITS[scope['state']]}。")
    if payload['omitted_count']:
        lines.append(f"另有 {payload['omitted_count']} 条匹配事件未展开。")
    return '\n'.join(lines)


def render_event_history(summary, execution, ledger):
    """Return a combined answer only with both matching, executed Tool receipts."""
    event = next((entry for entry in ledger.entries if entry.receipt.active_events_query_completed), None)
    history = next((entry for entry in ledger.entries if entry.receipt.history_query_completed), None)
    if event is None or history is None:
        return None
    events = execution.steps[event.execution_seq - 1].result.payload
    historical = execution.steps[history.execution_seq - 1].result.payload
    if events['sources'][0]['device_id'] != historical['device_id']:
        return None
    history_reply = render_history_summary(summary, execution, history)
    if history_reply is None:
        return None
    event_reply = render_empty_event_scope(events) or _positive_events(events)
    return f'{event_reply}\n\n本轮历史查询未提供可靠窗口总体均值。\n{history_reply}'
