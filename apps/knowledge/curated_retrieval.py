"""Retrieve cited Japanese-eel oxygen studies within their stated scope."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re
from unicodedata import normalize

from .evidence import KnowledgeEvidence, utcnow


_METRIC = re.compile(r"溶解氧|溶存氧|溶氧|dissolved[ _-]+oxygen|(?<![a-z0-9_])(?-i:DO)(?![a-z0-9_])", re.I)
_JAPANESE_EEL = r"(?:日本鳗(?:鲡|鱼)?(?![鲡鱼科目属])|\b(?:anguilla|a\.)[ \t]+japonica\b|\bjapanese eels?\b)"
_EEL = re.compile(
    _JAPANESE_EEL + r"|"
    r"(?:^|(?<=[ \t：:，、。的查问对看为是和与时])|(?<=溶氧)|(?<=一下))(?:鳗鲡|鳗鱼)(?![科目属])"
)
_OTHER_SPECIES = re.compile(
    r"(?:欧洲|美洲|非洲|印度|澳洲|新西兰|短鳍|花|双色|双斑)鳗|"
    r"(?:anguilla|(?<![a-z])a\.)[ \t]+(?!japonica\b)[a-z]+|european eel|american eel|"
    r"罗非鱼|虹鳟|鲤鱼|鲫鱼|鲈鱼|斑马鱼|泥鳅|黄鳝|虾|蟹|"
    r"\b(?:salmon|trout|tilapia|carp|catfish|zebrafish|shrimp|crabs?)\b"
)
_OTHER_METRIC = re.compile(r"水温|氨氮|亚硝酸盐|硝酸盐|酸碱度|盐度|浊度|二氧化碳|氮气|(?<![a-z])ph(?![a-z])")
_ON_SITE = re.compile(
    r"本池|我(?:们|家|的)?(?:这|那)?(?:口)?池|这口池|现在|当前|现场|本轮|实时|今天|鱼群实际|"
    r"\b(?:this|our|my)\s+(?:pond|farm|tank)\b"
)
_LITERATURE = re.compile(r"资料|文献|试验|实验|论文|研究|报告怎么说|stud(?:y|ies)|literature|paper")
_MIXED_TASK = re.compile(
    r"同时|另外|此外|再(?:查|问|看|告诉)|顺便|并(?:查|看|告诉|与|和)|样本(?:量|数)|"
    r"(?:过去|最近).{0,16}(?:监测|观测)|[?？;；]\s*\S|\b(?:also|additionally)\b"
)
_ACTION_REQUEST = re.compile(r"怎么喂|(?:是否要|要不要|应该|需不需要|可以|能否)(?:增氧|投喂|喂鱼)|处置|措施|建议")
_SUBJECT_JOIN = r"(?:和|与|及|或|对比|比较|相比|、|\b(?:and|or|versus|vs\.?)\b)"
_SUBJECT_JOIN_BEFORE = re.compile(rf"{_SUBJECT_JOIN}\s*$")
_SUBJECT_JOIN_AFTER = re.compile(rf"^\s*{_SUBJECT_JOIN}")
_OTHER_OUTCOME = re.compile(
    r"死亡|致死|存活|生存|成活|繁殖|产卵|孵化|浮头|病害|发病|感染|用药|治疗|"
    r"\b(?:mortality|death|survival|reproduction|spawning|hatching|disease|treatment)\b"
)
_NUMBER = r"[0-9]+(?:\.[0-9]+)?"
_RANGE_SEPARATOR = r"[-–—−~～至到]"
_SATURATION_SUBJECT = r"(?:溶解氧|溶存氧|溶氧|氧|空气)(?:的)?\s*"
_SATURATION_NAME = rf"{_SATURATION_SUBJECT}饱和度|(?:oxygen|air)\s+saturation"
_SATURATION_COPULA = r"(?:为|在|处于|达到|等于|是|[:=])?"
_SATURATION = re.compile(
    rf"{_SATURATION_NAME}|{_SATURATION_SUBJECT}{_SATURATION_COPULA}\s*"
    rf"(?:{_NUMBER}\s*%?\s*{_RANGE_SEPARATOR}\s*)?{_NUMBER}\s*%\s*饱和度"
)
_SATURATION_BEFORE = re.compile(rf"(?:{_SATURATION_NAME})\s*{_SATURATION_COPULA}\s*$")
_SATURATION_AFTER = re.compile(rf"^\s*的?\s*(?:{_SATURATION_NAME}|饱和度)")
_OUTCOMES = (
    ("feeding", re.compile(r"摄食|投喂|食欲|食量|停食|拒食|吃食|吃料|进食|喂食|采食|feed|appetite")),
    ("growth", re.compile(r"生长|体重|增重|增肥|长势|growth|weight")),
)

_UNIT_END = r"(?![a-z0-9])"
_CONCENTRATION_UNIT = rf"(?:mg\s*/\s*l|毫克\s*(?:每|/)\s*升){_UNIT_END}"
_SATURATION_UNIT = rf"%{_UNIT_END}"
_DIMENSION_SUFFIX = re.compile(r"^\s*(?:[/^*·⋅×%]|每(?:小?时|日|天|秒|分)|per\b|[-−–—]?\s*(?:h|hours?|s|d|days?)\b)")
_START = r"(?<![0-9.e+\-−–—])"
_OPERATORS = r"<=|>=|≤|≥|<|>|不低于|不高于|低于|高于|不超过|不少于"
_NUMERIC_PATTERNS = {
    key: (
        re.compile(rf"{_START}(?P<low>{_NUMBER})(?:\s*{unit})?\s*{_RANGE_SEPARATOR}\s*(?P<high>{_NUMBER})\s*{unit}"),
        re.compile(rf"{_START}(?P<op>{_OPERATORS})?\s*(?P<value>{_NUMBER})\s*{unit}"),
    )
    for key, unit in (("oxygen_intervals", _CONCENTRATION_UNIT), ("oxygen_saturation_intervals", _SATURATION_UNIT))
}
_SHORT_FOLLOWUP = re.compile(
    rf"(?:那(?:么)?\s*)?(?:{_OPERATORS})?\s*{_NUMBER}"
    rf"(?:\s*(?:{_CONCENTRATION_UNIT})?\s*{_RANGE_SEPARATOR}\s*{_NUMBER})?"
    rf"\s*{_CONCENTRATION_UNIT}\s*(?:呢|吗)?[?？。]?"
)
_GENERIC_TOPIC = re.compile(
    r"(?:请)?(?:查(?:一下)?|查询|查看|介绍|解释|资料怎么解释|项目资料怎么解释|那项目资料怎么解释|什么是)?\s*"
    r"(?:溶解氧|溶存氧|溶氧|dissolved[ _-]+oxygen|do)"
    r"(?:的(?:作用|资料|研究|定义)|(?:与|和)摄食(?:的关系|有什么关系)?)?[?？。]?"
)
_UNCERTAIN_VALUE = re.compile(r"约|左右|上下|附近|大概|以下|以上|差不多")
_NEGATED_SCOPE = re.compile(r"不问|别查|不要查|不用查|不是|并非|不等于|!=|≠")
_DIGIT = re.compile(r"[0-9]")
_HISTORY_COMPARISON = re.compile(
    r"(?P<paper>.+?)\s*(?:(?:,\s*(?:并\s*)?)|并\s*)(?:与|和|跟)\s*(?:最近|过去)\s*"
    r"(?P<window>(?:10|30|60)\s*分钟|半(?:个)?小时|(?:一|1)\s*(?:个)?小时)"
    r"\s*(?:的)?\s*(?:溶解氧|溶存氧|溶氧|DO)\s*(?:历史)?\s*(?:监测|观测)?\s*(?:数据|记录)?"
    r"\s*(?:进行)?(?:对比|比较)\s*[。.!?]?",
    re.I,
)
_PROJECT_LOOKUP_CLAUSE = re.compile(
    r"(?:请(?:你|帮我)?\s*)?(?:(?:麻烦(?:你)?|帮我)\s*)?(?:先\s*)?"
    r"(?:查(?:询|阅|找|证|一下|一查)?|检索|搜索|参考)\s*(?:一下\s*)?"
    r"(?:项目(?:内|的)?(?:养殖)?(?:资料|知识(?:库)?)|专题库|知识库)"
)
_FEEDING_POINT_CLAUSE = re.compile(
    rf"(?:请\s*)?(?:(?:给出|告诉我|查(?:询|一下)?)\s*)?{_JAPANESE_EEL}\s*(?:在)?\s*"
    rf"(?:溶解氧|溶存氧|溶氧|DO)\s*(?:为|是|在|[:=])?\s*(?P<point>{_NUMBER})\s*{_CONCENTRATION_UNIT}"
    r"\s*(?:时|(?:条件下))?\s*(?:的)?\s*(?:实验|试验)?(?:日)?摄食率\s*(?:是多少|为多少|多少)?\s*[。.!?]?",
    re.I,
)


@dataclass(frozen=True)
class OxygenHistoryComparison:
    paper_question: str
    point_mg_l: Decimal
    lookback_minutes: int


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
    """Return numeric presence and one interval with its explicit unit, if supported."""
    if not _DIGIT.search(text):
        return False, None
    if _UNCERTAIN_VALUE.search(text):
        return True, None

    saturation = _SATURATION.search(text)
    if saturation and "%" not in text:
        return True, None
    key = "oxygen_saturation_intervals" if saturation else "oxygen_intervals"
    range_pattern, value_pattern = _NUMERIC_PATTERNS[key]
    ranges = list(range_pattern.finditer(text))
    if len(ranges) > 1:
        return True, None
    if ranges:
        match = ranges[0]
        before, after = text[:match.start()], text[match.end():]
        # Other quantities may impose conditions outside this first literature slice.
        if _DIGIT.search(before + after):
            return True, None
        if (re.search(r"[<>=≤≥]|低于|高于|不超过|不少于", before)
                or _DIMENSION_SUFFIX.match(after)
                or saturation and not (_SATURATION_BEFORE.search(before) or _SATURATION_AFTER.match(after))):
            return True, None
        low, high = Decimal(match["low"]), Decimal(match["high"])
        return True, (key, OxygenInterval(low, high)) if low <= high else None

    values = list(value_pattern.finditer(text))
    if len(values) != 1:
        return True, None
    match = values[0]
    before, after = text[:match.start()], text[match.end():]
    if (_DIGIT.search(before + after) or _DIMENSION_SUFFIX.match(after)
            or saturation and not (_SATURATION_BEFORE.search(before) or _SATURATION_AFTER.match(after))
            or before.rstrip().endswith(("-", "−", "–", "—", "+", ".", "<", ">", "="))):
        return True, None
    value, operator = Decimal(match["value"]), match["op"]
    if operator in ("<", "低于", "<=", "≤", "不超过", "不高于"):
        return True, (key, OxygenInterval(None, value, False, operator in ("<=", "≤", "不超过", "不高于")))
    if operator in (">", "高于", ">=", "≥", "不少于", "不低于"):
        return True, (key, OxygenInterval(value, None, operator in (">=", "≥", "不少于", "不低于"), False))
    return True, (key, OxygenInterval(value, value))


def _display_number(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _display_interval(interval, unit):
    low, high = interval.low, interval.high
    if low == high:
        return f"实验点 {_display_number(low)} {unit}"
    if low is None:
        return f"{'不高于' if interval.high_inclusive else '低于'} {_display_number(high)} {unit} 的部分"
    if high is None:
        return f"{'不低于' if interval.low_inclusive else '高于'} {_display_number(low)} {unit} 的部分"
    left = "[" if interval.low_inclusive else "("
    right = "]" if interval.high_inclusive else ")"
    return f"{left}{_display_number(low)}, {_display_number(high)}{right} {unit} 的部分"


def _supported_scope(card, requested):
    if requested is None:
        return 2, ""
    key, interval = requested
    matches = [
        overlap for data in card.get(key, ())
        if (overlap := OxygenInterval.from_card(data).intersection(interval)) is not None
    ]
    if interval in matches:
        return 2, ""
    if matches:
        unit = "mg/L" if key == "oxygen_intervals" else "% 饱和度"
        display = "、".join(_display_interval(part, unit) for part in dict.fromkeys(matches))
        return 1, f"本条仅提供所问区间内的{display}证据，不能据此推断整个区间。"
    return 0, ""


def _topic(raw, text):
    return _METRIC.search(raw) or _SATURATION.search(text) or (_EEL.search(text) and re.search(r"低氧|缺氧", text))


def _unsupported(text):
    return (
        _OTHER_SPECIES.search(text) or _OTHER_METRIC.search(text) or _OTHER_OUTCOME.search(text)
        or _NEGATED_SCOPE.search(text)
        or any(_SUBJECT_JOIN_BEFORE.search(text[:match.start()]) or _SUBJECT_JOIN_AFTER.match(text[match.end():])
               for match in _EEL.finditer(text))
    )


def _outcomes(text):
    return {name for name, pattern in _OUTCOMES if pattern.search(text)}


def _standalone_oxygen(raw, text):
    return _topic(raw, text) and not (
        _ON_SITE.search(text) or _MIXED_TASK.search(text) or _OTHER_METRIC.search(text)
        or _ACTION_REQUEST.search(text)
    )


def is_standalone_oxygen_lookup(question: str) -> bool:
    """Recognize a single oxygen topic without confirming evidence coverage."""
    raw = normalize("NFKC", question)
    return bool(_standalone_oxygen(raw, raw.casefold().strip()))


def is_curated_quantitative_question(question: str) -> bool:
    """Recognize standalone, explicit literature questions for the bounded reply path."""
    raw = normalize("NFKC", question)
    text = raw.casefold().strip()
    return bool(
        _standalone_oxygen(raw, text) and _EEL.search(text) and len(_outcomes(text)) == 1
        and not _unsupported(text)
        and _request_interval(text)[1] is not None
    )


def parse_oxygen_history_comparison(question: str) -> OxygenHistoryComparison | None:
    """Recognize one published feeding point compared with an explicit history window."""
    match = _HISTORY_COMPARISON.fullmatch(normalize("NFKC", question).strip())
    if not match:
        return None
    paper_question = match["paper"].strip()
    # A single leading project-lookup clause may introduce the point query.
    # Match the full point clause so a second request cannot be lost when we render it.
    clauses = paper_question.split(",")
    if (len(clauses) > 2 or len(clauses) == 2 and not _PROJECT_LOOKUP_CLAUSE.fullmatch(clauses[0].strip())
            or not is_curated_quantitative_question(paper_question)):
        return None
    point = _FEEDING_POINT_CLAUSE.fullmatch(clauses[-1].strip())
    if not point:
        return None
    window = match["window"]
    minutes = (int(re.match(r"[0-9]+", window)[0]) if window.endswith("分钟")
               else 30 if window.startswith("半") else 60)
    return OxygenHistoryComparison(paper_question, Decimal(point["point"]), minutes)


def search_curated_oxygen(
    query: str, cards, *, top_k: int, retrieved_at: datetime | None = None, intent_text: str | None = None,
) -> tuple[KnowledgeEvidence, ...] | None:
    """Return curated evidence or None when the question is outside this structured domain."""
    raw_query = normalize("NFKC", query)
    raw_question = normalize("NFKC", intent_text) if intent_text is not None else raw_query
    normalized_query, question = raw_query.casefold(), raw_question.casefold().strip()
    has_numbers, requested = _request_interval(question)
    scope = question
    if not _topic(raw_question, question):
        if not _topic(raw_query, normalized_query):
            return None
        # Only a bare numeric follow-up can use the tool's topic hint. Its
        # explicit unit and interval still come from the user's own question.
        if requested is None or not _SHORT_FOLLOWUP.fullmatch(question):
            return ()
        scope = normalized_query
    if (top_k < 1 or _unsupported(scope) or (_ON_SITE.search(question) and not _LITERATURE.search(question))
            or not (_EEL.search(scope) or _GENERIC_TOPIC.fullmatch(scope))):
        return ()

    outcomes = _outcomes(scope)
    if has_numbers and (requested is None or not outcomes):
        return ()
    combined = f"{question}\n{normalized_query}"
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
