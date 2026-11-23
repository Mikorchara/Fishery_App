"""Retrieve cited Japanese-eel oxygen studies within their stated scope."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re
from unicodedata import normalize

from .evidence import KnowledgeEvidence, utcnow


_METRIC = re.compile(r"溶解氧|溶存氧|溶氧|dissolved[ _-]+oxygen|(?<![a-z0-9_])(?-i:DO)(?![a-z0-9_])", re.I)
_EEL = re.compile(r"鳗鲡|鳗鱼|日本鳗|anguilla|(?<![a-z])eels?(?![a-z])")
_OTHER_SPECIES = re.compile(
    r"(?:欧洲|美洲|非洲|印度|澳洲|新西兰|短鳍|花|双色|双斑)鳗|"
    r"(?:anguilla|(?<![a-z])a\.)[ \t]+(?!japonica\b)[a-z]+|european eel|american eel|"
    r"罗非鱼|虹鳟|鲤鱼|鲫鱼|鲈鱼|斑马鱼|泥鳅|黄鳝|虾|蟹|"
    r"\b(?:salmon|trout|tilapia|carp|catfish|zebrafish|shrimp|crabs?)\b"
)
_OTHER_METRIC = re.compile(r"水温|氨氮|亚硝酸盐|硝酸盐|酸碱度|盐度|浊度|二氧化碳|氮气|(?<![a-z])ph(?![a-z])")
_ON_SITE = re.compile(r"本池|我(?:家|的)?(?:这|那)?(?:口)?池|这口池|现在|当前|现场|本轮|实时|实测|今天|鱼群实际")
_LITERATURE = re.compile(r"资料|文献|试验|实验|论文|研究|报告怎么说|stud(?:y|ies)|literature|paper")
_OUTCOMES = (
    ("feeding", re.compile(r"摄食|投喂|食欲|吃食|吃料|进食|喂食|采食|feed|appetite")),
    ("growth", re.compile(r"生长|体重|增重|增肥|长势|growth|weight")),
)

_NUMBER = r"[0-9]+(?:\.[0-9]+)?"
_UNIT = r"(?:mg\s*/\s*l(?![a-z0-9/^])|毫克\s*(?:每|/)\s*升)"
_START = r"(?<![0-9.e+\-−–—])"
_RANGE = re.compile(
    rf"{_START}(?P<low>{_NUMBER})(?:\s*{_UNIT})?\s*[-–—−~～至到]\s*(?P<high>{_NUMBER})\s*{_UNIT}"
)
_VALUE = re.compile(
    rf"{_START}(?P<op><=|>=|≤|≥|<|>|不低于|不高于|低于|高于|不超过|不少于)?\s*(?P<value>{_NUMBER})\s*{_UNIT}"
)
_UNCERTAIN_VALUE = re.compile(r"约|左右|上下|附近|大概|以下|以上|差不多")
_NEGATED_SCOPE = re.compile(r"不问|别查|不要查|不用查|不是|并非|不等于|!=|≠")
_DIGIT = re.compile(r"[0-9]")


@dataclass(frozen=True)
class OxygenInterval:
    low: Decimal | None
    high: Decimal | None
    low_inclusive: bool = True
    high_inclusive: bool = True

    @classmethod
    def from_card(cls, data):
        return cls(
            Decimal(data["low"]) if data["low"] is not None else None,
            Decimal(data["high"]) if data["high"] is not None else None,
            data["low_inclusive"],
            data["high_inclusive"],
        )

    def intersection(self, other):
        low = other.low if self.low is None else (
            self.low if other.low is None else max(self.low, other.low)
        )
        high = other.high if self.high is None else (
            self.high if other.high is None else min(self.high, other.high)
        )
        low_inclusive = low is not None and (
            (self.low != low or self.low_inclusive) and (other.low != low or other.low_inclusive)
        )
        high_inclusive = high is not None and (
            (self.high != high or self.high_inclusive) and (other.high != high or other.high_inclusive)
        )
        if low is not None and high is not None and (
            low > high or (low == high and not (low_inclusive and high_inclusive))
        ):
            return None
        return OxygenInterval(low, high, low_inclusive, high_inclusive)


def _request_interval(text):
    """Return whether numeric conditions are present and the single safe condition, if any."""
    if not _DIGIT.search(text):
        return False, None
    if _UNCERTAIN_VALUE.search(text):
        return True, None

    ranges = list(_RANGE.finditer(text))
    if len(ranges) > 1:
        return True, None
    if ranges:
        match = ranges[0]
        # Other quantities may impose conditions outside this first literature slice.
        if _DIGIT.search(text[:match.start()] + text[match.end():]):
            return True, None
        if re.search(r"[<>=≤≥]|低于|高于|不超过|不少于", text[:match.start()]):
            return True, None
        low, high = Decimal(match["low"]), Decimal(match["high"])
        return True, OxygenInterval(low, high) if low <= high else None

    values = list(_VALUE.finditer(text))
    if len(values) != 1:
        return True, None
    match = values[0]
    before, after = text[:match.start()], text[match.end():]
    if _DIGIT.search(before + after) or before.rstrip().endswith(("-", "−", "–", "—", "+", ".", "<", ">", "=")):
        return True, None
    value, operator = Decimal(match["value"]), match["op"]
    if operator in ("<", "低于", "<=", "≤", "不超过", "不高于"):
        return True, OxygenInterval(None, value, False, operator in ("<=", "≤", "不超过", "不高于"))
    if operator in (">", "高于", ">=", "≥", "不少于", "不低于"):
        return True, OxygenInterval(value, None, operator in (">=", "≥", "不少于", "不低于"), False)
    return True, OxygenInterval(value, value)


def _display_number(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _display_interval(interval):
    low, high = interval.low, interval.high
    if low == high:
        return f"实验点 {_display_number(low)} mg/L"
    if low is None:
        return f"{'不高于' if interval.high_inclusive else '低于'} {_display_number(high)} mg/L 的部分"
    if high is None:
        return f"{'不低于' if interval.low_inclusive else '高于'} {_display_number(low)} mg/L 的部分"
    left = "[" if interval.low_inclusive else "("
    right = "]" if interval.high_inclusive else ")"
    return f"{left}{_display_number(low)}, {_display_number(high)}{right} mg/L 的部分"


def _supported_scope(card, requested):
    if requested is None:
        return 2, ""
    matches = [
        overlap for data in card["oxygen_intervals"]
        if (overlap := OxygenInterval.from_card(data).intersection(requested)) is not None
    ]
    if requested in matches:
        return 2, ""
    if matches:
        display = "、".join(_display_interval(part) for part in dict.fromkeys(matches))
        return 1, f"本条仅提供所问区间内的{display}证据，不能据此推断整个区间。"
    return 0, ""


def search_curated_oxygen(
    query: str, cards, *, top_k: int, retrieved_at: datetime | None = None, intent_text: str | None = None,
) -> tuple[KnowledgeEvidence, ...] | None:
    """Return curated evidence or None when the question is outside this structured domain."""
    raw_query = normalize("NFKC", query)
    raw_question = normalize("NFKC", intent_text) if intent_text is not None else raw_query
    normalized_query, question = raw_query.casefold(), raw_question.casefold()
    combined = f"{question}\n{normalized_query}"
    if not (_METRIC.search(raw_query) or _METRIC.search(raw_question)
            or (_EEL.search(combined) and re.search(r"低氧|缺氧", combined))):
        return None
    # When the caller knows the original question, a model's rewrite may not turn
    # a request for current pond observations into a literature query.
    if (
        top_k < 1 or _OTHER_SPECIES.search(combined) or _OTHER_METRIC.search(combined)
        or _NEGATED_SCOPE.search(question)
        or (_ON_SITE.search(question) and not _LITERATURE.search(question))
    ):
        return ()

    has_numbers, requested = _request_interval(question)
    if not has_numbers and question != normalized_query:
        has_numbers, requested = _request_interval(normalized_query)
    if has_numbers and requested is None:
        return ()

    outcomes = {name for name, pattern in _OUTCOMES if pattern.search(combined)}
    ranked = []
    for card in cards:
        if card["species"] != "anguilla_japonica" or (outcomes and outcomes.isdisjoint(card["outcomes"])):
            continue
        support, scope = _supported_scope(card, requested)
        if not support:
            continue
        keyword_hits = sum(
            normalize("NFKC", keyword).casefold() in combined for keyword in set(card["keywords"])
        )
        ranked.append((support, keyword_hits, card["id"], scope, card))
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))

    timestamp = retrieved_at or utcnow()
    return tuple(
        KnowledgeEvidence(
            evidence_id=card["id"], text=f"{scope}\n{card['body']}" if scope else card["body"],
            category="water_quality", score=float(support), source_id=card["source_url"],
            source_title=card["title"], source_version=card["source_version"], retrieved_at=timestamp,
        )
        for support, _, _, scope, card in ranked[:top_k]
    )
