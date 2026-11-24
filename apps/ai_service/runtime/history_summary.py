"""Answer explicitly scoped historical water questions from the verified Tool result."""

from dataclasses import dataclass
from datetime import timedelta, timezone
from math import isclose
import re

from apps.monitoring.contracts import METRICS, timestamp

from ..business_tools.water_quality_history import WATER_QUALITY_HISTORY


_BEIJING = timezone(timedelta(hours=8))
_MINUTES = {'10': 10, '十': 10, '30': 30, '三十': 30, '60': 60, '六十': 60}
_METRICS = {'溶解氧': 'dissolved_oxygen_mg_l', '溶氧': 'dissolved_oxygen_mg_l',
    '水温': 'temperature_c', 'ph': 'ph'}
_QUESTION = re.compile(
    r'(?:请|请问|帮我)?(?:查一下|查询|看看|看一下|汇总)?\s*'
    r'(?:最近|过去|近)\s*(?:(?P<minutes>10|30|60|十|三十|六十)\s*分钟|(?P<hours>半|一|1)小时)'
    r'\s*的?\s*(?P<metric>溶解氧|溶氧|水温|pH)\s*的?\s*'
    r'(?:(?P<extreme>最低|最高)(?:值|的窗口均值)(?:出现在哪个窗口|出现在什么时候|是什么时候|在什么时候|是多少|在哪|何时)?'
    r'|历史(?:变化|走势|汇总|统计)?|变化(?:如何|怎么样)?|走势(?:如何|怎么样)?|(?:有)?什么变化|统计(?:结果)?|汇总|变化趋势(?:如何)?)',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HistorySummary:
    minutes: int
    metric: str
    extreme: str | None

    def instruction(self):
        return (f'本轮问题只涉及最近 {self.minutes} 分钟的单项历史水质。'
                f'请用 {WATER_QUALITY_HISTORY}，参数 lookback_minutes={self.minutes}，metrics=["{self.metric}"]。'
                '取得该历史结果后即可回答。覆盖不足时说明本轮历史的缺口，勿调用当前水质或其他工具补齐。')


def history_summary_for_turn(request, policy):
    if request.history or not policy.allows(WATER_QUALITY_HISTORY):
        return None
    match = _QUESTION.fullmatch(request.question.strip().rstrip('？?。！!').rstrip())
    if match is None:
        return None
    minutes = _MINUTES[match['minutes']] if match['minutes'] else 30 if match['hours'] == '半' else 60
    return HistorySummary(minutes, _METRICS[match['metric'].lower()], match['extreme'])


def _range(start, end):
    return (f'{start.astimezone(_BEIJING):%Y-%m-%d %H:%M:%S} 至 '
            f'{end.astimezone(_BEIJING):%Y-%m-%d %H:%M:%S}')


def _value(number, unit):
    return f'{number:.12g} {unit}' if unit else f'{number:.12g}'


def _coverage_limits(stat, start, end):
    gaps = stat['gaps']
    items, omitted = gaps['items'], gaps['omitted_count']
    if type(items) is not list or type(omitted) is not int or omitted < 0 or gaps['count'] != len(items) + omitted:
        raise ValueError('invalid history gap count')
    previous = start
    ranges = []
    visible_seconds = 0
    for item in items:
        left, right = timestamp(item['start']), timestamp(item['end'])
        if item['reason'] != 'NO_RELIABLE_METRIC' or not previous <= left < right <= end:
            raise ValueError('invalid history gap range')
        ranges.append(_range(left, right))
        visible_seconds += (right - left).total_seconds()
        previous = right
    missing_seconds = (end - start).total_seconds() - stat['reliable_window_s']
    total = gaps['total_s']
    if (type(total) not in (int, float) or not isclose(total, missing_seconds, abs_tol=1e-6)
            or visible_seconds > total + 1e-6 or not omitted and not isclose(visible_seconds, total, abs_tol=1e-6)):
        raise ValueError('invalid history gap duration')
    if ranges:
        detail = f'缺少可靠观测的时段包括{"、".join(ranges[:2])}。'
        remaining = len(ranges) + omitted - min(2, len(ranges))
        return detail + (f'另有 {remaining} 处缺口。' if remaining else '')
    return f'有 {omitted} 处缺口，具体时段未展开。' if omitted else ''


def render_history_summary(summary, execution, entry):
    """Match the requested period and metric before reading statistics from the receipt."""
    label, unit, *_ = METRICS[summary.metric]
    if entry is None:
        return None
    receipt = entry.receipt
    start, end = timestamp(receipt.history_range_start), timestamp(receipt.history_range_end)
    payload = execution.steps[entry.execution_seq - 1].result.payload
    stat = payload['metrics'].get(summary.metric)
    if end - start != timedelta(minutes=summary.minutes) or stat is None:
        return None

    scope = f"设备 {payload['device_id']} 的模拟{label}历史（北京时间 {_range(start, end)}）。"
    count = stat['reliable_windows']
    if not count:
        detail = ('本次没有完整匹配的历史窗口。' if payload['status'] == 'NO_DATA'
                  else '本次没有该指标的可靠历史窗口。')
        return f'{scope}{detail}'

    if summary.extreme:
        field = 'min_window_mean' if summary.extreme == '最低' else 'max_window_mean'
        ref = stat[field]
        span = _range(timestamp(ref['window_start']), timestamp(ref['window_end']))
        result = f'本次可靠窗口中，{summary.extreme}均值为 {_value(ref["value"], unit)}，首次对应窗口为北京时间 {span}。'
    else:
        first, last = (_value(stat[field]['window_mean'], unit) for field in ('first', 'last'))
        low, high = (_value(stat[field]['value'], unit) for field in ('min_window_mean', 'max_window_mean'))
        result = f'可靠窗口的首末均值为 {first} 和 {last}，窗口均值范围为 {low} 至 {high}。'
    coverage = f'共 {count} 个可靠窗口，覆盖 {stat["reliable_coverage_ratio"]:.1%} 的查询时段。'
    try:
        limits = _coverage_limits(stat, start, end)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        limits = '缺口时段暂时无法核实。'
    if payload['status'] == 'PARTIAL' and not limits:
        limits = '查询结果为部分覆盖，存在数据质量或连续性限制。'
    return f'{scope}\n\n{result}{coverage}{limits}'
