"""Match explicit event questions and report limitations from this turn's evidence."""

from dataclasses import dataclass
from datetime import timedelta, timezone
from enum import Enum
import re

from apps.monitoring.contracts import METRICS, timestamp
from apps.monitoring.water_contracts import Freshness, Quality

from ..business_tools.current_water_quality import CURRENT_WATER_QUALITY, WATER_TOOL_PROJECTION


class EventAccess(Enum):
    DISABLED = "本次服务未启用当前事件查询，无法核实当前事件。"
    UNSUPPORTED_MODE = "当前问答模式未提供当前事件查询，本轮无法核实当前事件。"
    NOT_AUTHORIZED = "当前事件查询工具在本轮未获授权，无法核实当前事件。"


_BEIJING = timezone(timedelta(hours=8))
_EVENT_NOUN = r'(?:(?:(?:还在|正在)发生的|未结束的)?事件|活动事件|活跃事件|异常事件|告警|异常)'
_CURRENT = r'(?:当前|现在|目前)'
_CURRENT_EVENT_QUESTION = re.compile(
    rf'(?:请问|帮我看看|帮我查一下)?{_CURRENT}(?:鱼塘|养殖池|设备)?(?:还)?'
    rf'(?:有什么|有哪些|是否有|有没有|有无|有){_EVENT_NOUN}(?:还没有结束|还在发生|吗)?'
    rf'|(?:请问)?{_CURRENT}(?:的)?{_EVENT_NOUN}(?:有哪些|有什么)'
    rf'|(?:请|帮我)?(?:查看|查询|检查|查一下|看看){_CURRENT}(?:的)?{_EVENT_NOUN}'
    rf'|{_CURRENT}(?:还在|正在)发生的事件'
    rf'|(?:请问)?{_CURRENT}发生(?:了)?(?:什么|哪些)事件(?:了)?(?:吗)?'
)
_MIXED_SEPARATOR = re.compile(r'[,，;；。？?！!]')
_MIXED_CONNECTOR = re.compile(r'^(?:顺便|同时|另外|接着|先查(?:一下)?|再|并且?)\s*')
_CURRENT_WATER_METRIC = re.compile(
    rf'(?:请问|请|帮我)?(?:查一下|查询|看看|看一下|告诉我)?\s*{_CURRENT}(?:的)?(?:鱼塘|养殖池|设备)?\s*'
    r'(?P<metric>溶解氧|溶存氧|溶氧|pH|酸碱度|水温)(?:\s*值)?\s*(?:(?:是|为)?(?:多少|什么数值)|读数)',
    re.IGNORECASE,
)
_CURRENT_METRIC_IDS = {
    '溶解氧': 'dissolved_oxygen_mg_l', '溶存氧': 'dissolved_oxygen_mg_l', '溶氧': 'dissolved_oxygen_mg_l',
    'ph': 'ph', '酸碱度': 'ph', '水温': 'temperature_c',
}


def requires_active_events(question):
    """Recognize explicit current event queries for the mandatory source gate."""
    return isinstance(question, str) and bool(
        _CURRENT_EVENT_QUESTION.fullmatch(question.strip().rstrip('？?。！!').rstrip())
    )


def event_metric_query(question):
    """Match exactly one current-event request and one explicit current metric."""
    if not isinstance(question, str):
        return None
    clauses = _MIXED_SEPARATOR.split(question.strip().rstrip('？?。！!').rstrip())
    if len(clauses) != 2:
        return None
    left, right = (_MIXED_CONNECTOR.sub('', clause.strip()) for clause in clauses)
    if requires_active_events(right):
        left, right = right, left
    metric = _CURRENT_WATER_METRIC.fullmatch(right) if requires_active_events(left) else None
    return _CURRENT_METRIC_IDS[metric['metric'].lower()] if metric else None


def render_current_metric(execution, entry, metric):
    """Use the same valid, fresh, online reading in either event reply path."""
    label, unit, *_ = METRICS[metric]
    unavailable = f"本轮未取得可用于核实当前{label}的模拟水质观测。"
    if entry is None or metric not in entry.receipt.available_fields:
        return unavailable

    observation = entry.receipt
    payload = execution.steps[entry.execution_seq - 1].result.payload
    if (payload.get("projection_version") != WATER_TOOL_PROJECTION
            or payload.get("source_kind") != "simulator"
            or observation.freshness != Freshness.FRESH
            or observation.quality not in (Quality.VALID, Quality.PARTIAL)
            or payload.get("connectivity") != "online"
            or payload.get("metrics", {}).get(metric, {}).get("quality") != "valid"):
        return unavailable

    value = payload["water_quality"][metric]
    observed = timestamp(observation.observed_at).astimezone(_BEIJING)
    reading = f"{value} {unit}" if unit else str(value)
    return (f"模拟水质设备 {payload['device_id']} 的最新有效观测显示，{label}为 {reading}。"
            f"观测时间为北京时间 {observed:%Y-%m-%d %H:%M:%S}。")


@dataclass(frozen=True)
class EventNotice:
    access: EventAccess
    metric: str | None = None

    def __post_init__(self):
        if not isinstance(self.access, EventAccess) or self.metric is not None and self.metric not in METRICS:
            raise ValueError("invalid event capability notice")

    def instruction(self, water_allowed: bool) -> str:
        if self.metric is None:
            return self.access.value + "本轮只问当前事件，用一句话交代限制。无需调用其他工具。"
        if not water_allowed:
            return self.access.value + "当前水质查询也不在本轮权限内，分别说明这两项限制。"
        label = METRICS[self.metric][0]
        return (self.access.value + f"用户同时询问当前{label}，用已授权的 {CURRENT_WATER_QUALITY} 查询。"
                "结论限定在本轮实际取得的水质观测。")

    def render(self, execution, ledger, *, water_allowed: bool) -> str:
        text = self.access.value
        if self.metric is None:
            return text

        if not water_allowed:
            label = METRICS[self.metric][0]
            return f"{text}\n\n当前水质查询在本轮未获授权，无法核实当前{label}。"

        entry = next((entry for entry in ledger.entries
                     if entry.receipt.tool_name == CURRENT_WATER_QUALITY
                     and entry.receipt.observation_query_completed), None)
        return f"{text}\n\n{render_current_metric(execution, entry, self.metric)}"
