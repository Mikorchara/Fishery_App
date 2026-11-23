"""Knowledge Tool definition, strict query contract and bounded Evidence mapping."""
import re

from apps.ai_backend.model_gateway import ModelToolDefinition


SEARCH_FISHERY_KNOWLEDGE = "search_fishery_knowledge"

KNOWLEDGE_DESCRIPTION = (
    "只读检索项目内鳗鲡养殖背景知识；用于用户明确要求查询项目资料，或回答依赖项目特有资料的问题。"
    "query应表达要检索的主题。返回有限背景证据及来源，不代表当前水质或现场事实，不诊断现场疾病，不负责当前评分。"
    "NO_MATCH表示检索正常完成但无合格命中，不是执行错误；不得编造命中内容。"
)

KNOWLEDGE_PARAMETERS = {
    "type": "object",
    "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 512}},
    "required": ["query"],
    "additionalProperties": False,
}

KNOWLEDGE_DEFINITION = ModelToolDefinition(SEARCH_FISHERY_KNOWLEDGE, KNOWLEDGE_DESCRIPTION, KNOWLEDGE_PARAMETERS)
RESULT_INSTRUCTION = (
    "把 evidence 当作项目背景资料，仅引用相关条目的内容和实际来源。"
    "说明匹配内容与用户问题的关系，保留原资料的条件和适用范围。"
    "NO_MATCH 表示本轮在项目资料中未检索到符合条件的条目。"
    "背景资料无法证明当前水质、现场状况或疾病诊断。"
)


KNOWLEDGE_BINDING_VERSION = "management-project-knowledge@2"
CURATED_OXYGEN_CONTRACT = "eel-oxygen-result@1"
_LOOKUP_VERB = r"(?:查询|检索|查阅|查找|查证|查(?:一下|一查)?|搜索|参考)(?:一下)?"
_PROJECT_SOURCE = r"(?:项目(?:内|的)?(?:养殖)?(?:资料|知识(?:库)?)|专题库|知识库)"
_EXPLICIT_LOOKUP = re.compile(
    r"(?:^|[。！？!?，,；;])\s*(?:请(?:你)?\s*)?(?:麻烦(?:你)?\s*)?(?:帮我\s*)?(?:先|再)?\s*"
    rf"(?:{_LOOKUP_VERB}\s*{_PROJECT_SOURCE}|(?:从|在)\s*{_PROJECT_SOURCE}(?:里|中|内)?\s*{_LOOKUP_VERB})"
)


def requires_project_lookup(question: str) -> bool:
    return bool(_EXPLICIT_LOOKUP.search(question))

# Existing query validation and bounded result mapping; retrieval remains in KnowledgeService.


TOP_K = 3               # Fixed server-side budget; never a model-supplied parameter.
MAX_TEXT_CHARS = 800    # Per evidence text, counted in CHARACTERS (not UTF-8 bytes).
MAX_QUERY_CHARS = 512   # Declared parameter bound; 512 CJK chars is 1536 UTF-8 bytes.
TRUNCATION_MARK = "\u2026"


def _is_rejected_character(character: str) -> bool:
    """True for C0/C1 controls (Cc) and lone surrogates (Cs).

    Written as explicit code-point ranges so this module keeps zero imports: it
    depends only on the injected service.
    """
    code = ord(character)
    return code <= 0x1F or 0x7F <= code <= 0x9F or 0xD800 <= code <= 0xDFFF


def validate_arguments(arguments: dict) -> dict:
    """Server-side parameter contract for this tool: reject, or return normalized input.

    The Executor runs this before the handler, so anything rejected here never
    reaches retrieval. Only ``query`` is declared - never ``top_k``, a backend, a
    threshold, a path, a URL or a module name. The 4096-byte argument ceiling is
    already enforced by the Executor, so no separate byte budget is needed here.
    """
    if not isinstance(arguments, dict) or set(arguments) != {"query"}:
        raise ValueError("only the query field is accepted")
    query = arguments["query"]
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    query = query.strip()
    if not query:
        raise ValueError("query must not be blank")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError("query is too long")
    if any(_is_rejected_character(character) for character in query):
        raise ValueError("query must not contain control or surrogate characters")
    return {"query": query}


def search_fishery_knowledge(arguments: dict, *, service, question=None) -> dict:
    """Map one validated query to bounded background evidence.

    ``arguments`` is already normalized by the tool's declared argument contract:
    exactly one key, ``query`` (rejection and normalization belong to that
    contract, not here). Retrieval itself stays inside ``KnowledgeService`` - this
    handler never re-implements indexing, expansions, thresholds or a second
    index. Evidence text is untrusted data: it is passed through as data only and
    never interpreted as instructions.

    Returns ``OK`` with bounded items, or ``NO_MATCH`` with an empty list when the
    service reports no qualifying evidence. Service failures are not caught here.
    """
    options = {}
    curated = False
    if question is not None:
        from apps.knowledge.curated_retrieval import (
            is_curated_quantitative_question, is_standalone_oxygen_lookup,
        )
        from apps.knowledge.service import KnowledgeContentService

        if isinstance(service, KnowledgeContentService):
            options['question'] = question
    if options and requires_project_lookup(question) and is_standalone_oxygen_lookup(question):
        evidence, structured = service.search_with_scope(arguments["query"], top_k=TOP_K, **options)
        curated = structured and (not evidence or is_curated_quantitative_question(question))
    else:
        evidence = service.search(arguments["query"], top_k=TOP_K, **options)
    items = [{"id": item.evidence_id, "category": item.category, "source": item.source_id,
              "source_version": item.source_version, "text": _bounded_text(item.text)}
             for item in evidence]
    result = {"status": "OK" if items else "NO_MATCH",
            # Effective backend, passed through as-is: it tells the model which
            # retrieval backend produced these items. Never inferred or composed here.
            "retrieval_mode": service.backend,
            "result_count": len(items),
            "evidence": items}
    if curated:
        coverage = "NO_MATCH" if not items else "PARTIAL" if any(item.score < 2 for item in evidence) else "EXACT"
        result["curated_oxygen"] = {"contract": CURATED_OXYGEN_CONTRACT, "coverage": coverage}
    return result


def render_curated_oxygen_result(payload: dict) -> str | None:
    """Render only the bounded results produced by the structured knowledge tool."""
    scope = payload.get("curated_oxygen")
    if not isinstance(scope, dict) or scope.get("contract") != CURATED_OXYGEN_CONTRACT:
        return None
    coverage = scope.get("coverage")
    if coverage == "NO_MATCH" and payload["status"] == "NO_MATCH":
        return "本次在专题库中未找到符合所问条件的实验资料。"
    if coverage in ("EXACT", "PARTIAL") and payload["status"] == "OK":
        introduction = ("本次只找到所问范围内的部分实测点。"
                        if coverage == "PARTIAL" else "本次找到对应的实验资料。")
        citations = [f"{item['text']}\n来源 {item['source']}" for item in payload["evidence"]]
        return "\n\n".join([introduction, *citations])
    return None


def _bounded_text(text: str) -> str:
    """Truncate in characters. The longest live chunk is 415 chars / 844 bytes."""
    return text if len(text) <= MAX_TEXT_CHARS else text[:MAX_TEXT_CHARS] + TRUNCATION_MARK
