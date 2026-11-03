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
    description=('只读计算当前绑定设备的实验水质评分、等级和分项依据；内部只读取一次当前水质，不必再调用当前水质查询。'
        '溶解氧50%，水温25%，pH25%；复用Monitoring规则结果，严重异常限制总分。'
        '必须完整、有效、新鲜且正常上报；缺测、无效、过期或离线返回NOT_SCORABLE，不补正常分、不用旧历史。'
        'NO_DATA为没有观测。评分由程序计算，不允许模型自创分数或阈值；必须说明来源、时间和非专业标准。'),
    parameters={'type':'object','properties':{},'additionalProperties':False})


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
