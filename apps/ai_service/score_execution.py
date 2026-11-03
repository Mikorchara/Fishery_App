"""Independent, opt-in Web score trial; never inherits three-tool qualification."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tools.policy import ToolPolicy
from apps.ai_backend.tool_conversation import ToolExecutionMode,ToolModelTransport
from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION
from .business_tools.registry import HISTORY_CANDIDATE_TOOL_NAMES,WATER_QUALITY_SCORE
from .business_tools import water_quality_score as scoring
from .execution import ExecutionDecision,management_scope
from .normal_selection import normal_selection_scope,UNIFIED_PRESET
from .runtime.release_contracts import AssistantExecutionProfile,_json,_hash
from .runtime.streaming_contracts import streaming_scope

SCORE_TOOL_NAMES=(*HISTORY_CANDIDATE_TOOL_NAMES,WATER_QUALITY_SCORE)
CONTRACT='management-score-tool-trial@1'


def score_scope(profile,registry,knowledge,transport):
    policy=ToolPolicy('assistant',True,SCORE_TOOL_NAMES)
    scope={**normal_selection_scope(profile,registry,knowledge),**management_scope(profile,policy,registry,knowledge)}
    if transport==ToolModelTransport.STREAMING:
        scope['runtime']=streaming_scope(profile,policy,registry,DEFAULT_HISTORY_PROJECTION)
        scope['budget']={**scope['budget'],'max_output_tokens':512}
    scope['transport']=transport.value
    scope['score_contract']={'version':scoring.SCORING_VERSION,'source':scoring.SOURCE_CONTRACT,
        'weights':scoring.WEIGHTS,'points':scoring.POINTS,'caps':scoring.CAPS,
        'eligibility':'COMPLETE_VALID_FRESH_ONLINE_RULE_EVIDENCE',
        'implementation':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in (
            ('scoring',Path(scoring.__file__)),('admission',Path(__file__)),
            ('monitoring_rules',Path(scoring.__file__).parents[2]/'monitoring/rules.py'),
            ('diagnosis',Path(scoring.__file__).parents[2]/'monitoring/diagnosis.py'),
            ('source_gate',Path(__file__).parent/'runtime/sources.py'))}}
    return scope


@dataclass(frozen=True)
class ScoreTrialConfig:
    scopes_json:tuple[str,...]
    enabled:bool=False

    def __post_init__(self):
        if (type(self.enabled) is not bool or type(self.scopes_json) is not tuple or len(self.scopes_json)!=4
                or len(set(self.scopes_json))!=4):raise GatewayError('INVALID_SCORE_TRIAL_CONFIG')
        try:
            for raw in self.scopes_json:
                value=json.loads(raw)
                if value['runtime']['tools']!=list(SCORE_TOOL_NAMES) or value['score_contract']['version']!=scoring.SCORING_VERSION:
                    raise ValueError()
        except (ValueError,TypeError,KeyError):raise GatewayError('INVALID_SCORE_TRIAL_CONFIG') from None


def load_score_config(*,enable_trial=False):
    try:
        path=Path(__file__).with_name('resources')/'assistant_score_trial.json'
        value=json.loads(path.read_bytes() if path.stat().st_size<=65536 else b'')
        if (set(value)!={'contract','status','enabled','qualification_id','validated_at','scopes'}
                or value['contract']!=CONTRACT or value['status']!='local_experimental' or value['enabled'] is not False
                or value['qualification_id'] is not None or value['validated_at'] is not None):raise ValueError()
        return ScoreTrialConfig(tuple(_json(s) for s in value['scopes']),enable_trial)
    except (ValueError,TypeError,KeyError,OSError):raise GatewayError('INVALID_SCORE_TRIAL_CONFIG') from None


def resolve_score_trial(config,profile,policy,registry,knowledge,*,device_id,epoch,policy_revision,transport):
    scope=score_scope(profile,registry,knowledge,transport)
    matched=(profile.preset_id==UNIFIED_PRESET and _json(scope) in config.scopes_json
        and WATER_QUALITY_SCORE in policy.exposed_tools and set(policy.exposed_tools)<=set(SCORE_TOOL_NAMES))
    reason='active' if matched and config.enabled else 'flag_disabled' if not config.enabled else 'scope_not_published'
    revision=_hash({'trial':CONTRACT,'scope':scope,'enabled':config.enabled,'tools':list(policy.exposed_tools),
        'device':device_id,'epoch':epoch,'policy_revision':policy_revision})
    return ExecutionDecision(AssistantExecutionProfile(ToolExecutionMode.BOUNDED_MULTI_ROUND,revision,
        'local_experimental',reason),matched and config.enabled,transport,
        512 if transport==ToolModelTransport.STREAMING else 1024)
