"""Web-style natural answer, with notes derived from actual per-Tool receipts."""
import re
import unicodedata

from .channel_chat_presentation import _time, STATES, LABELS
from .hybrid_presentation import HybridPresentation
from .business_tools.active_events import ACTIVE_EVENTS
from .business_tools.current_water_quality import CURRENT_WATER_QUALITY
from .business_tools.water_quality_history import WATER_QUALITY_HISTORY
from .business_tools.fishery_knowledge import SEARCH_FISHERY_KNOWLEDGE
from .business_tools.water_quality_score import WATER_QUALITY_SCORE

CONTRACT = 'management-qq-web-agent-reply@1'
MAX_REPLY_CHARS = 1500
_EVENT_LOOKUP_CLAIM = re.compile(
    r'(?:已经|已)(?:成功)?(?:查询|读取|查到|检索)(?:了)?(?:本轮|当前|实时|现在|现场|鱼塘)?(?:的)?'
    r'(?:(?:正在|还在)发生的|活跃|活动|异常)?(?:事件|告警|异常)'
)


def _event_note(payload, receipt):
    summaries = []
    for source in payload['sources']:
        label = 'SIMULATOR' if source['source_kind'] == 'simulator' else '设备报告'
        counts = f"活动 {source['active_count']} 条、待核实 {source['uncertain_count']} 条、待复核 {source['review_count']} 条"
        observations = source['observations']
        coverage = '、'.join(('水质' if item['channel'] == 'water' else '视觉') +
            (f" {_time(item['observed_at'])}（{STATES[item['freshness']]}）" if item['observed_at'] else ' 尚无观测')
            for item in observations)
        summaries.append(f"{label} · {source['device_id']}：{counts}；观测 {coverage}。")
    note = f'事件查询 · 评估 {_time(receipt.evaluated_at)}：' + ''.join(summaries)
    if receipt.active_events_status == 'NO_DATA':
        note += '没有可用观测，无法判断当前状态。'
    elif receipt.active_events_status == 'NO_ACTIVE_EVENTS':
        note += '已查询范围内未查到符合条件的事件。'
    else:
        note += '检测信号需人工核查。'
    if receipt.active_events_omitted_count:
        note += f'另有 {receipt.active_events_omitted_count} 条未展开。'
    return note


def source_notes(steps, receipts):
    """No second query, computed rule, invented score or merged single receipt."""
    notes=[]
    for step, receipt in zip(steps, receipts):
        payload=step.result.payload
        if receipt.tool_name in (CURRENT_WATER_QUALITY,WATER_QUALITY_SCORE):
            quality=payload['data_quality']
            note='SIMULATOR · '+payload['device_id']+'；观测 '+_time(receipt.observed_at)
            note+='；'+ '/'.join(STATES.get(quality.get(v),'未知') for v in ('quality','freshness','connectivity'))
            note+='；查询未重新采样。'
            limited=[LABELS[key]+' '+STATES.get(metric.get('quality'),'未知')
                     for key,metric in payload.get('metrics',{}).items()
                     if key in LABELS and metric.get('quality')!='valid']
            if limited:note+=' '+ '、'.join(limited)+'。'
            if receipt.tool_name==WATER_QUALITY_SCORE:
                note+=' 实验评分：'+(str(payload['score'])+' / '+str(payload['grade'])
                    if receipt.has_score else '不可评分（'+str(payload['status'])+'）')+'；非专业标准。'
            hits=[f['message']+'（'+{'critical':'严重','warning':'提醒','info':'提示'}.get(f.get('severity'),'未知')+'）'
                  for f in payload.get('findings',())
                  if f.get('kind')=='WATER_RISK' and f.get('state')=='HIT']
            if hits:note+=' 规则：'+'；'.join(hits)+'。'
            if receipt.observed_at is None:note+=' 尚无观测，不能确认当前状态。'
            elif quality['quality']!='valid' or quality['freshness']!='fresh' or quality['connectivity']!='online':
                note+=' 数据不足以完整确认当前状态。'
        elif receipt.tool_name==WATER_QUALITY_HISTORY:
            note='历史窗口（SIMULATOR）：'+_time(receipt.history_range_start)+' 至 '+_time(receipt.history_range_end)
            note+='；'+str(receipt.history_window_count)+'个窗口；'+payload['status']+'；历史不代表当前。'
        elif receipt.tool_name == ACTIVE_EVENTS:
            note = _event_note(payload, receipt)
        else:
            note='项目知识：'+str(receipt.evidence_count)+'条背景证据'
            if not receipt.has_project_evidence:note+='（无合格命中）'
            else:
                sources=list(dict.fromkeys(str(item['source'])[:80] for item in payload.get('evidence',())))
                note+='；来源 '+'、'.join(sources)
            note+='；不是现场事实或疾病确诊。'
        notes.append(note)
    return tuple(notes)


def _execution_claim_error(text, receipts):
    """Only explicit execution impersonation; not a semantic truth classifier."""
    normalized=unicodedata.normalize('NFKC',text).casefold()
    current=any(r.observation_query_completed for r in receipts)
    history=any(r.history_query_completed for r in receipts)
    knowledge=any(r.project_search_completed for r in receipts)
    events=any(r.active_events_query_completed for r in receipts)
    for part in re.split(r'[。！？!?；;，,\n]|但是|然而|不过|但',normalized):
        clause=re.sub(r'\s+','',part)
        if (clause.endswith(('吗','么','呢')) or clause.startswith(('如果','假设','假如','若','例如','是否','你是想问'))
                or re.search(r'(?:没有|尚未|不能|无法|不会|未曾|未)(?:执行|操作|开启|关闭|查询|读取|确认)',clause)):
            continue
        if re.search(r'(?:已|已经)(?:成功)?(?:开启|启动|关闭|停止|控制|调节|删除|修改|确认事件|完成处置|执行操作)',clause):
            return 'AGENT_UNSUPPORTED_OPERATION_CLAIM'
        if _EVENT_LOOKUP_CLAIM.search(clause):
            if not events:
                return 'AGENT_EVENT_SOURCE_MISSING'
            clause = _EVENT_LOOKUP_CLAIM.sub('', clause)
        if not current and re.search(r'(?:我|本助手|系统|本轮)(?:已经|已)(?:查询|读取|检测|采样)(?:了)?(?:现场|当前|实时|鱼塘|水质|传感器)|(?:已|已经)(?:查询|读取)(?:了)?(?:当前|实时|现场)',clause):
            return 'AGENT_CURRENT_SOURCE_MISSING'
        if not history and re.search(r'(?:已|已经)(?:查询|读取|统计)(?:了)?(?:历史|过去\d|最近\d)',clause):
            return 'AGENT_HISTORY_SOURCE_MISSING'
        if not knowledge and re.search(r'(?:已|已经)(?:检索|查询)(?:了)?(?:项目资料|项目知识|知识库)',clause):
            return 'AGENT_KNOWLEDGE_SOURCE_MISSING'
    return None


def present(result):
    text=result.model_text
    error=None
    if type(text) is not str or not text.strip():error='AGENT_EMPTY_REPLY'
    elif any(unicodedata.category(c) in ('Cc','Cf','Cs') and c not in '\n\t' for c in text):
        error='AGENT_INVALID_TEXT'
    else:error=_execution_claim_error(text,result.receipts)
    notes='\n'.join(result.source_notes)
    suffix=('\n\n本轮来源（北京时间 UTC+08）：\n'+notes) if notes else '\n（AI回答；本轮未读取现场或项目资料。）'
    rendered=(text.strip()+suffix) if not error else ''
    if not error and len(rendered)>MAX_REPLY_CHARS:error='AGENT_REPLY_TOO_LONG'
    if error:
        messages={
            'AGENT_EMPTY_REPLY':'模型没有返回完整答复，请重新提问；没有自动重试。',
            'AGENT_INVALID_TEXT':'模型答复包含无法显示的字符，未展示正文。',
            'AGENT_CURRENT_SOURCE_MISSING':'本轮没有取得现场查询依据，不能将这段回答作为当前水质结论。可发送 /当前水质直接查询。',
            'AGENT_HISTORY_SOURCE_MISSING':'本轮没有执行历史查询，未展示声称已经查询历史的答复。',
            'AGENT_EVENT_SOURCE_MISSING':'本轮没有取得事件查询依据，无法确认当前事件。',
            'AGENT_KNOWLEDGE_SOURCE_MISSING':'本轮没有检索项目资料，未展示声称已检索的答复。',
            'AGENT_UNSUPPORTED_OPERATION_CLAIM':'当前工具只有只读权限，没有执行设备控制、删除或配置修改。',
            'AGENT_REPLY_TOO_LONG':'答复超过QQ单条消息长度，请缩小问题范围；没有自动重新推理。'}
        fallback=messages[error]+ ('\n本轮实际来源：\n'+notes if notes else '')
        return HybridPresentation(fallback,error,False,result.branch,False,bool(notes))
    return HybridPresentation(rendered,'AGENT_NATURAL_REPLY_ACCEPTED',True,result.branch,True)
