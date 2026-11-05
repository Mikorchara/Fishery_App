"""QQ plain-language rendering of the shared Agent result.

The receipt proves which read ran, not the truth of every model sentence.
Small explicit-claim guards are defence in depth, not a fact verifier.
"""
import math
import re
import unicodedata

from .channel_chat_presentation import LABELS, STATES, _time
from .hybrid_presentation import HybridPresentation

CONTRACT = 'management-qq-natural-reply@1'
MAX_REPLY_CHARS = 1500  # Leaves room for the existing offline delivery label.
REFUSAL = '本轮AI答复未能安全展示，请换一种问法；查询当前读数也可发送 /当前水质。'


def source_note(source):
    """Only the current trusted Tool result supplies this authoritative note."""
    lines = [f'系统来源：SIMULATOR 模拟数据 · {source.device_id}']
    values = []
    for metric in source.metrics:
        valid = (metric.quality == 'valid' and type(metric.value) in (int, float)
                 and math.isfinite(metric.value))
        value = f'{metric.value:g} {metric.unit}'.strip() if valid else '数据不足（' + STATES.get(metric.quality, '未知') + '）'
        values.append(LABELS[metric.id] + ' ' + value)
    lines.append('；'.join(values))
    lines.append(f'观测 {_time(source.observed_at)}；评估 {_time(source.evaluated_at)}（北京时间 UTC+08）。')
    lines.append('状态：' + '/'.join(STATES.get(v, '未知') for v in
        (source.quality, source.freshness, source.connectivity)) + '；查询未重新采样。')
    if source.status == 'NO_DATA':
        lines.append('尚无观测，不能确认当前水质。')
    elif not source.current_evidence_usable:
        lines.append('当前状态不能完整确认；过期/离线读数仅供回看，缺测不作正常。')
    if source.rule_hits:
        lines.append('系统实验规则：' + '；'.join(r.message + '（' +
            {'critical': '严重', 'warning': '提醒', 'info': '提示'}.get(r.severity, r.severity) + '）'
            for r in source.rule_hits) + '。')
    elif source.current_evidence_usable:
        lines.append('本窗口未命中水质实验规则，不代表专业健康或适养保证。')
    else:
        lines.append('未见当前规则命中不能证明没有风险。')
    return '\n'.join(lines)


def _clauses(text):
    normalized = unicodedata.normalize('NFKC', text).casefold()
    return [re.sub(r'\s+', '', value) for value in re.split(r'[。！？!?；;，,\n]|但是|然而|不过|但', normalized)]


def _explicit_claim_error(text, source):
    for clause in _clauses(text):
        # These narrowly target affirmative completion claims. Ordinary concepts,
        # numerical examples and denials are allowed; no business-keyword gate.
        if (clause.endswith(('吗', '么', '呢'))
                or clause.startswith(('是否', '能否', '你是想问', '如果', '假设', '假如', '若', '例如'))
                or re.search(r'(?:当前|现在|目前).{0,12}(?:是否|能否|有没有|是不是)', clause)):
            continue
        if re.search(r'(?:没有|尚未|不能|无法|不会|未曾|未)(?:执行|操作|开启|关闭|查询|读取|确认)', clause):
            # Split contrast separately so a denial cannot exempt a following
            # affirmative clause, such as “未查询，但我已经确认当前水质正常”。
            continue
        if re.search(r'(?:已|已经)(?:成功)?(?:开启|启动|关闭|停止|控制|调节|删除|修改|确认事件|完成处置|执行操作)', clause):
            return 'NATURAL_UNSUPPORTED_OPERATION_CLAIM'
        if source is None:
            if re.search(r'(?:我|本助手|系统|本轮)(?:已经|已)(?:查询|读取|检测|采样)|(?:已|已经)(?:查询|读取)(?:了)?(?:当前|实时|现场|你[的们]?鱼塘)', clause):
                return 'NATURAL_OBSERVATION_REQUIRED'
            if re.search(r'(?:当前|现在|目前|此刻|实时)(?:你[的们]?|该|本)?(?:鱼塘|池塘|水质|设备|溶解氧|溶氧|水温|ph).{0,12}(?:(?:为|是|[:：])?[-+]?\d|正常|安全|在线|离线|无风险|已恢复)', clause):
                return 'NATURAL_OBSERVATION_REQUIRED'
            if re.search(r'(?:你的|该|本)(?:鱼塘|池塘).{0,12}(?:正常|安全|无风险)', clause):
                return 'NATURAL_OBSERVATION_REQUIRED'
            if re.search(r'i(?:have)?(?:already)?(?:queried|checked|read)(?:the)?(?:current|live|sensor|pond)|(?:current|live)(?:pond|water)(?:is|:)(?:normal|safe)', clause):
                return 'NATURAL_OBSERVATION_REQUIRED'
        else:
            if re.search(r'(?:来源|采集自|来自|这是)(?:真实|实际)(?:硬件|传感器|设备采样)', clause):
                return 'NATURAL_SIMULATOR_SOURCE_CONFLICT'
            if not source.current_evidence_usable and re.search(
                    r'(?:当前|现在|实时)(?:鱼塘|池塘|水质|数据|监测|读数).{0,12}(?:完全正常|安全无忧|均正常|全部正常|实时有效)', clause):
                return 'NATURAL_STALE_CLAIM_CONFLICT'
    return None


def present(result):
    text = result.model_text
    if type(text) is not str or not text.strip():
        error = 'NATURAL_EMPTY_REPLY'
    elif any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs') and c not in '\n\t' for c in text):
        error = 'NATURAL_INVALID_TEXT'
    elif text.lstrip().startswith(('{', '```')):
        error = 'NATURAL_PLAIN_TEXT_REQUIRED'
    else:
        error = _explicit_claim_error(text, result.source)
    source = result.source
    if source is None:
        rendered = text.strip() + '\n（AI一般回答；本轮未查询现场数据。）' if not error else REFUSAL
        if len(rendered) > MAX_REPLY_CHARS:
            error, rendered = 'NATURAL_REPLY_TOO_LONG', 'AI答复超过QQ单条消息长度，请缩小问题范围；没有自动重试。'
        return HybridPresentation(rendered, error or 'NATURAL_GENERAL_ACCEPTED', not error,
                                  'general', not error)
    note = source_note(source)
    rendered = ('AI答复（模型解释，未逐句核验）：\n' + text.strip() + '\n\n' + note) if not error else note
    if len(rendered) > MAX_REPLY_CHARS:
        error = 'NATURAL_REPLY_TOO_LONG'
    if error:
        # Do not truncate away provenance or send an unsupported model answer.
        return HybridPresentation('AI解释未展示，仅提供本轮系统事实。\n' + note,
                                  error, False, 'water', False, True)
    return HybridPresentation(rendered, 'NATURAL_WATER_ACCEPTED', True, 'water', True)
