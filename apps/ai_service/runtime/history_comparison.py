"""Select a self-reported reading in the server-bound QQ conversation."""

from dataclasses import dataclass, field
from decimal import Decimal
import re

from apps.monitoring.contracts import METRICS

from .event_notice import current_metric_data, render_current_metric


OXYGEN = 'dissolved_oxygen_mg_l'
_ALIASES = {'ph': 'ph', '溶解氧': OXYGEN}
CLARIFICATION = '你想比 pH 还是溶解氧？'
_EXPLICIT = re.compile(
    r'(?:跟|和|与)(?:这段(?:已保留的)?对话(?:里|中))?我(?:最近一次|上一次|上次)'
    r'(?:记录|记下)的\s*(?P<metric>pH|溶解氧)\s*(?:比|比较|相比)(?:一下|呢|差多少)?', re.IGNORECASE)
_ADJACENT = re.compile(r'(?:那)?(?:跟|和|与)(?:上一次|上次)(?:比|相比|比较)(?:一下|呢|差多少)?')
_STATEMENT = re.compile(
    r'(?:设备\s+(?P<device>[A-Za-z0-9][A-Za-z0-9_-]{0,63})\s*[：:]\s*)?'
    r'我(?:先前|此前|上次|刚才|这次)?(?:手动)?(?:记录|记下)的\s*(?P<metric>pH|溶解氧)'
    r'\s*(?:是|为|[：:])\s*(?P<number>[0-9]{1,3}(?:\.[0-9]{1,6})?)\s*(?P<unit>mg\s*/\s*l)?', re.IGNORECASE)


@dataclass(frozen=True)
class HistoryComparison:
    metric: str | None
    prior_index: int | None = None
    value: Decimal | None = field(default=None, repr=False)


def _readings(user, device_id):
    readings = {}
    for part in re.split('[。；;\n]+', user.strip().rstrip('。；;')):
        match = _STATEMENT.fullmatch(part.strip())
        if not match or match['device'] not in (None, device_id):
            return {}
        metric = _ALIASES[match['metric'].lower()]
        value = Decimal(match['number'])
        unit = re.sub(r'\s+', '', match['unit'] or '').lower()
        if metric in readings or unit != METRICS[metric][1].lower() or not METRICS[metric][2] <= value <= METRICS[metric][3]:
            return {}
        readings[metric] = value
    return readings


def comparison_for_history(question, history, device_id):
    """Use the latest unambiguous record within the available conversation."""
    query = question.strip().rstrip('？?。！!').strip()
    explicit = _EXPLICIT.fullmatch(query)
    if explicit:
        metric = _ALIASES[explicit['metric'].lower()]
        label = METRICS[metric][0].lower()
        for index in range(len(history) - 1, -1, -1):
            user = history[index].user
            readings = _readings(user, device_id)
            if metric in readings:
                return HistoryComparison(metric, index, readings[metric])
            if label in user.lower() and re.search(r'[0-9]', user):
                break  # A more recent user statement is ambiguous or differently bound.
        return HistoryComparison(metric)
    if history and _ADJACENT.fullmatch(query):
        readings = _readings(history[-1].user, device_id)
        if len(readings) == 1:
            metric, value = next(iter(readings.items()))
            return HistoryComparison(metric, len(history) - 1, value)
        if len(readings) == 2:
            return HistoryComparison(None)
    return None


def render_comparison(comparison, execution, entry):
    current = render_current_metric(execution, entry, comparison.metric)
    if comparison.value is None:
        return current + '\n本段保留对话中没有可明确匹配的自述旧读数，暂时无法比较。'
    label, unit, *_ = METRICS[comparison.metric]
    suffix = f' {unit}' if unit else ''
    previous = f'你在旧对话中自述的{label}读数为 {comparison.value:f}{suffix}。'
    data = current_metric_data(execution, entry, comparison.metric)
    if data is None:
        return f'{current}\n{previous}暂时无法计算变化。'
    delta = Decimal(str(data[1])) - comparison.value
    if delta:
        direction = '上升' if delta > 0 else '下降'
        change = f'与该自述值相比，读数{direction} {abs(delta):f}{suffix}。'
    else:
        change = '本轮读数与该自述值相同。'
    return f'{current}\n{previous}{change}'
