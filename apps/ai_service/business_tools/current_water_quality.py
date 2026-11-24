"""Current water Tool with one capture and a detached Monitoring DTO."""
from dataclasses import asdict
from apps.ai_backend.model_gateway import ModelToolDefinition

CURRENT_WATER_QUALITY = "get_current_water_quality"

WATER_TOOL_PROJECTION = "management-current-water@1"

WATER_DEFINITION = ModelToolDefinition(
    name=CURRENT_WATER_QUALITY,
    description=("只读查询绑定设备的最新水质快照。问当前水温、pH、溶解氧、水质状态或明确的水质告警时用本工具。"
                 "返回读数、数据质量、新鲜度、观测时间和规则结果。无需重新采样，参数传 {}。"),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
)
RESULT_INSTRUCTION = (
    "先回答所问指标或水质告警。取 water_quality 的对应值、metrics 的单位和单项质量，注明来源、设备和观测时间（带时区）。"
    "只问当前水质数值、状态或告警时，本工具已返回所需范围，直接回答，即使结果缺测或过期也不要转查项目资料。"
    "observed_at 是观测时间，勿以 last_reported_at 或 evaluated_at 代替。"
    "NO_DATA 表示暂无观测。缺测、无效、过期或离线导致无法核实当前值时，先说明限制；"
    "过期读数按旧观测标明时间，勿用对话中的旧值补足。部分有效时只报告可用指标并说明缺口。"
    "告警按对应 findings 状态。HIT 是规则命中，CLEAR 是未命中该规则，证据不足或未评估则无法判断。"
    "追问原因时说明规则用了什么观测；依据未提供实际成因时直说无法确定。"
)


def water_payload(monitoring, device_id):
    return project_water_tool(monitoring.capture_water(device_id))


def project_water_tool(capture):
    """Detached Tool DTO from one capture; no Web history, fetch or diagnosis."""
    analysis, reading = capture.analysis, capture.reading
    ref, quality = analysis.observation, analysis.data_quality
    result = {"projection_version": WATER_TOOL_PROJECTION,
        "status": "OK" if ref else "NO_DATA", "water_quality": None,
        "device_id": analysis.device_id, "channel": analysis.channel, "batch_id": ref.batch_id if ref else None,
        "source_kind": ref.source_kind if ref else "simulator",
        "evaluated_at": analysis.evaluated_at, "last_reported_at": capture.last_reported_at,
        "connectivity": quality.connectivity, "data_quality": asdict(quality),
        "rule_version": capture.rule_version, "findings": []}
    if ref is None:
        return result
    result.update({"water_quality": {
        **{m.id: getattr(reading, m.id) for m in capture.metrics},
        "quality": reading.quality.value, "freshness": reading.freshness.value,
        "observed_at": reading.observed_at.isoformat(), "retrieved_at": reading.retrieved_at.isoformat(),
        "source": reading.source},
        "window": {"start": ref.window_start, "end": ref.window_end, "duration_s": ref.window_duration_s},
        "aggregation": ref.aggregation, "statistics_version": ref.statistics_version,
        "metrics": {m.id: {"unit": m.unit, "quality": m.quality,
            "invalid_samples": m.invalid_samples} for m in capture.metrics},
        # All outcomes matter, especially insufficient evidence / not evaluated.
        # Observation identity is shared above, not repeated for every finding.
        "findings": [{"code": f.code, "kind": f.kind, "state": f.state.value,
            "severity": f.severity, "message": f.message, "facts_used": list(f.facts_used),
            "reason": f.reason, "rule": asdict(f.rule)} for f in analysis.findings]})
    return result
