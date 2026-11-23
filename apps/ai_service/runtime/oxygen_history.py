"""Evidence-bound reply for an explicit literature point and oxygen history comparison."""

from datetime import timedelta, timezone
from decimal import Decimal

from apps.knowledge.curated_retrieval import parse_oxygen_history_comparison
from apps.monitoring.contracts import timestamp

from ..business_tools.fishery_knowledge import render_curated_oxygen_result


_BEIJING = timezone(timedelta(hours=8))
_OXYGEN = "dissolved_oxygen_mg_l"


def render_oxygen_history_comparison(question, execution, ledger):
    """Use only the correlated payloads whose receipts the existing ledger accepted."""
    comparison = parse_oxygen_history_comparison(question)
    if comparison is None:
        return None

    paper_entry = next((entry for entry in ledger.entries if entry.receipt.project_search_completed), None)
    if paper_entry is None:
        return None
    paper_payload = execution.steps[paper_entry.execution_seq - 1].result.payload
    paper = render_curated_oxygen_result(paper_payload)
    if paper is None:
        return None

    history_entry = next((entry for entry in ledger.entries if entry.receipt.history_query_completed), None)
    missing = f"本轮未取得所问 {comparison.lookback_minutes} 分钟的溶氧历史，无法比较。"
    if history_entry is None:
        return f"{paper}\n\n{missing}"

    receipt = history_entry.receipt
    history = execution.steps[history_entry.execution_seq - 1].result.payload
    start = timestamp(receipt.history_range_start)
    end = timestamp(receipt.history_range_end)
    stats = history["metrics"].get(_OXYGEN)
    if end - start != timedelta(minutes=comparison.lookback_minutes) or stats is None:
        return f"{paper}\n\n{missing}"

    period = (f"{start.astimezone(_BEIJING):%Y-%m-%d %H:%M:%S} 至 "
              f"{end.astimezone(_BEIJING):%Y-%m-%d %H:%M:%S}")
    scope = f"设备 {history['device_id']} 的模拟水质历史（北京时间 {period}）。"
    if not stats["reliable_windows"]:
        return f"{paper}\n\n{scope}该时段没有可靠的溶氧窗口均值，无法比较。"

    low = Decimal(str(stats["min_window_mean"]["value"]))
    high = Decimal(str(stats["max_window_mean"]["value"]))
    limits = "历史查询为部分覆盖，" if history["status"] == "PARTIAL" else ""
    series = (f"{scope}{limits}溶氧可靠覆盖 {stats['reliable_coverage_ratio']:.2%}。"
              f"{stats['reliable_windows']} 个可靠窗口的均值范围为 {low:f}–{high:f} mg/L。")
    missing_seconds = history["coverage"]["requested_s"] - stats["reliable_window_s"]
    if missing_seconds > 0:
        series += f"约 {missing_seconds:.1f} 秒未被可靠窗口覆盖。"

    point = comparison.point_mg_l
    if paper_payload["curated_oxygen"]["coverage"] != "EXACT":
        return f"{paper}\n\n{series}缺少对应的论文测点，无法比较。"
    if low > point:
        relation = f"这些窗口均值均高于论文的 {point:f} mg/L 测点。"
    elif high < point:
        relation = f"这些窗口均值均低于论文的 {point:f} mg/L 测点。"
    else:
        relation = f"论文的 {point:f} mg/L 测点落在这些窗口均值的范围内。"
    return (f"{paper}\n\n{series}\n\n{relation}此次比较只反映已留存的模拟历史与论文测点，"
            "现场摄食情况仍需现场观测。")
