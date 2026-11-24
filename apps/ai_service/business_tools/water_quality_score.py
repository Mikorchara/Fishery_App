"""Experimental, deterministic score of one captured current-water observation.

No sensor thresholds live here: HIT/CLEAR evidence belongs to Monitoring.
An incomplete or non-current observation never receives an overall score.
"""
import math
from apps.ai_backend.model_gateway import ModelToolDefinition
from apps.monitoring.rules import WATER_RULES
from .current_water_quality import project_water_tool

WATER_QUALITY_SCORE = 'score_current_water_quality'
SCORING_VERSION = 'management-water-score@1'
SOURCE_CONTRACT = 'management-water-score-source@1'
WEIGHTS = {'temperature':25,'ph':25,'dissolved_oxygen':50}
FIELDS = {'temperature':'temperature_c','ph':'ph','dissolved_oxygen':'dissolved_oxygen_mg_l'}
POINTS = {'clear':100,'warning':60,'critical':20,'extreme':0}
CAPS = {'clear':100,'warning':79,'critical':39,'extreme':19}
LIMITATION = 'EXPERIMENTAL / NOT PROFESSIONAL STANDARD：仅汇总本窗口已评估水质规则；不是鱼群健康、疾病、长期趋势或养殖适宜性保证。'
SCORE_DEFINITION = ModelToolDefinition(name=WATER_QUALITY_SCORE,
    description=('问当前实验水质总分、等级、分项或封顶依据时使用。本工具只读，直接使用绑定设备当前快照，'
        '返回程序评分或不可评分原因。仅问评分时无需另查当前水质。参数传 {}。'),
    parameters={'type':'object','properties':{},'additionalProperties':False})
RESULT_INSTRUCTION = (
    "首句直接说明本轮能否评分。有评分时使用 score 与 grade_label 原值。"
    "用相关 components 或命中的规则解释主要影响项；若 score_cap 实际限制了总分，"
    "区分 weighted_score 加权分与 score 最终分，只引用程序已给出的分数、等级和上限。"
    "NOT_SCORABLE 时明确当前不可评分，依据 unscorable_reasons 解释原因，"
    "过期观测可与设备在线并存，不把旧观测当作当前依据，也不估算分数或等级。"
    "NO_DATA 时说明本轮没有观测。存在观测时，根据实际字段交代来源和设备。"
    "说明评分仅是本窗口已评估水质规则的实验汇总，为非专业标准。等级不能用于判断现场鱼群是否健康或水质是否长期适宜。\n"
    "若被问加权分与总分为什么不同且确有封顶，按顺序说明加权分、触发封顶的最严重分项及其命中规则、"
    "程序上限与最终分。components 的最严重 level 决定上限；rule_codes 相应规则用于说明具体风险。"
    "界面或消息的来源区会显示观测时间。正文只在用户明确询问时间时引用 water_quality.observed_at，"
    "原样保留年月日、时间和偏移，不换算，不使用 evaluated_at 代替。过期时明确这是旧观测。"
)


def _finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def eligibility(payload):
    """Same pure evidence gate for computation and Receipt validation."""
    water=payload.get('water_quality')
    if not isinstance(water,dict):return ['NO_DATA']
    reasons=[]
    if water.get('quality')!='valid':reasons.append('INCOMPLETE_OR_INVALID')
    if water.get('freshness')!='fresh':reasons.append('NOT_FRESH')
    if payload.get('connectivity')!='online':reasons.append('NOT_ONLINE')
    quality=payload.get('data_quality',{})
    if (quality.get('quality')!=water.get('quality') or quality.get('freshness')!=water.get('freshness')
            or quality.get('connectivity')!=payload.get('connectivity')):reasons.append('DATA_QUALITY_MISMATCH')
    metrics=payload.get('metrics',{})
    findings=payload.get('findings',[])
    for field,codes in WATER_RULES.items():
        value=water.get(field)
        if not _finite(value) or metrics.get(field,{}).get('quality')!='valid':
            reasons.append('METRIC_NOT_RELIABLE');continue
        evidence=[f for f in findings if f.get('kind')=='WATER_RISK' and f.get('code') in codes]
        if (len(evidence)!=len(codes) or {f['code'] for f in evidence}!=set(codes)
                or any(f.get('state') not in ('HIT','CLEAR') or
                       (f['state']=='HIT' and f.get('severity') not in ('warning','critical')) for f in evidence)):
            reasons.append('RULE_EVIDENCE_INCOMPLETE')
    return sorted(set(reasons))


def evaluation(payload):
    reasons=eligibility(payload)
    if reasons:return dict(score=None,grade=None,grade_label='不可评分',components={},
                           unscorable_reasons=reasons,weighted_score=None,score_cap=None)
    components={};worst='clear'
    order=tuple(POINTS)
    for name,field in FIELDS.items():
        hits=[f for f in payload['findings'] if f.get('kind')=='WATER_RISK' and
              f.get('code') in WATER_RULES[field] and f['state']=='HIT']
        level=('extreme' if any(f['code']=='OXYGEN_CRITICAL_EXTREME' for f in hits) else
               'critical' if any(f['severity']=='critical' for f in hits) else 'warning' if hits else 'clear')
        if order.index(level)>order.index(worst):worst=level
        components[name]=dict(score=POINTS[level],weight_percent=WEIGHTS[name],
            value=payload['water_quality'][field],unit=payload['metrics'][field]['unit'],
            level=level,rule_codes=[f['code'] for f in hits])
    # Integer weights and points: no floating-point budget/rounding ambiguity.
    weighted=sum(c['score']*c['weight_percent'] for c in components.values())/100
    score=min(weighted,CAPS[worst])
    grade='GOOD' if worst=='clear' else 'WARNING' if worst=='warning' else 'CRITICAL'
    return dict(score=score,grade=grade,grade_label={'GOOD':'已评估规则未见异常','WARNING':'需关注','CRITICAL':'需重点核查'}[grade],
        components=components,unscorable_reasons=[],weighted_score=weighted,score_cap=CAPS[worst])


def valid_evaluation(payload):
    if payload.get('scoring_version')!=SCORING_VERSION:return False
    try:
        expected=evaluation(payload)
        return all(payload.get(k)==v for k,v in expected.items()) and payload.get('status')==(
            'NO_DATA' if payload.get('water_quality') is None else 'NOT_SCORABLE' if expected['score'] is None else 'OK')
    except (KeyError,TypeError,ValueError,AttributeError,OverflowError):return False


def score_payload(monitoring,device_id):
    payload=project_water_tool(monitoring.capture_water(device_id))
    water=payload['water_quality']
    payload.update(scoring_version=SCORING_VERSION,score_source_contract=SOURCE_CONTRACT,
        quality=water['quality'] if water else None,freshness=water['freshness'] if water else None,
        query_evaluated_at=payload['evaluated_at'],experimental=True,limitation=LIMITATION)
    payload.update(evaluation(payload))
    payload['status']='NO_DATA' if water is None else 'NOT_SCORABLE' if payload['score'] is None else 'OK'
    if water is None:payload['evaluated_at']=None
    return payload
