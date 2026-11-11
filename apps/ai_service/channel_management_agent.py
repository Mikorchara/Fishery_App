"""QQ access to the existing Web Agent and explicitly authorized read tools."""
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolExecutionMode, ToolExecutionStep, ModelExecutionStep
from apps.ai_backend.tools import ToolDefinition, ToolRegistry
from apps.ai_backend.tools.policy import ToolPolicy
from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION
from apps.monitoring.contracts import identifier
from .active_event_execution import ACTIVE_EVENT_PROMPT
from .business_tools.active_events import ACTIVE_EVENTS, ACTIVE_EVENTS_DEFINITION, ACTIVE_EVENTS_PROJECTION
from .business_tools.current_water_quality import WATER_DEFINITION, CURRENT_WATER_QUALITY
from .business_tools.fishery_knowledge import KNOWLEDGE_DEFINITION, SEARCH_FISHERY_KNOWLEDGE
from .business_tools.water_quality_history import HISTORY_DEFINITION, WATER_QUALITY_HISTORY
from .business_tools.water_quality_score import SCORE_DEFINITION, WATER_QUALITY_SCORE
from .channel import ChannelAssistantResult
from .channel_hybrid import HybridHistorySnapshot
from .channel_management_continuous import ContinuousChannelBudget, ContinuousManagementTurn, prepared_scope as previous_scope
from .channel_validation import implementation_sha256
from .channel_trial import PRESET, QwenTrialSession
from .execution import ExecutionDecision
from .runtime.assistant import assistant_profile
from .runtime.release_contracts import AssistantExecutionProfile, _hash, release_scope
from .runtime.sources import TurnSourceReceipt
from .channel_agent_presentation import present, CONTRACT as PRESENTATION_CONTRACT

CONTRACT = 'management-qq-web-agent-run@1'
PROMPT_ID = 'QQ_MANAGEMENT_WEB_AGENT@2'
_DEFINITIONS = (WATER_DEFINITION, KNOWLEDGE_DEFINITION, HISTORY_DEFINITION, SCORE_DEFINITION, ACTIVE_EVENTS_DEFINITION)
TOOLS = tuple(definition.name for definition in _DEFINITIONS)
INSTRUCTION = ACTIVE_EVENT_PROMPT[1] + (
    '你以鳗鲡养殖智能体的身份在QQ群交流，自然、直接地回答问题，可用简短分段。'
    '不要求JSON、固定报告或General/Water标签。普通概念和养殖解释可直接回答。'
    '当前读数、当前事件、历史统计、项目知识和实验评分各用对应可用工具；参数依其定义，设备由服务器固定。'
    '当前水质、事件和评分工具参数为{}；历史工具只接受lookback_minutes(10/30/60)和可选metrics；'
    '知识工具只接受query，不接受路径、设备或权限。实验评分是程序计算的参考，不是专业标准。'
    '历史窗口统计和项目知识不能证明当前水质，若比较历史与现在应分别查询；'
    '评分工具已包含本轮当前观测，不必为同一评分重复查询当前水质。'
    'Tool来源为SIMULATOR时如实说明；缺测、过期、离线和NO_DATA/NO_MATCH不能解释为正常或已命中。'
    '需要的来源超出本轮预算时说明尚缺信息，不编造。系统会附本轮实际查询来源，不必复述全部技术字段。'
    '只能读取，不执行ACK、删除、规则修改、设备控制或通过聊天切换设备和权限。')


@dataclass(frozen=True)
class AgentChannelBudget(ContinuousChannelBudget):
    """Separate identity; the prior current-only continuous budget is unchanged."""


def prepared_scope(options, output_tokens=2048):
    budget = AgentChannelBudget(output_tokens)
    base = previous_scope(options, output_tokens)
    registry = ToolRegistry(ToolDefinition(d, lambda *_: None) for d in _DEFINITIONS)
    runtime = release_scope(assistant_profile(PRESET), ToolPolicy('assistant', True, TOOLS),
                            registry, DEFAULT_HISTORY_PROJECTION)
    runtime.update(prompt_id=PROMPT_ID, prompt_sha256=_hash(INSTRUCTION))
    root = Path(__file__).resolve().parents[2]
    paths = ('apps/ai_service/channel_management_agent.py', 'apps/ai_service/channel_agent_presentation.py',
             'apps/ai_service/runtime/assistant.py', 'apps/ai_service/runtime/sources.py',
             'apps/ai_service/business_tools/registry.py', 'apps/ai_service/business_tools/fishery_knowledge.py',
             'apps/ai_service/business_tools/water_quality_history.py', 'apps/ai_service/business_tools/water_quality_score.py',
             'apps/knowledge/repository.py', 'apps/knowledge/service.py', 'apps/knowledge/retrieval.py',
             'apps/qq_bot/knowledge_source.py', 'apps/qq_bot/agent_conversations.py',
             'apps/ai_service/active_event_execution.py', 'apps/ai_service/business_tools/active_events.py',
             'apps/monitoring/event_cycles.py', 'apps/monitoring/event_families.py',
             'apps/monitoring/manual_end.py')
    return {**base, 'contract': CONTRACT, 'runtime': runtime,
        'execution': {'mode': 'BOUNDED_MULTI_ROUND', 'max_tool_calls': 2, 'max_tool_rounds': 2,
                       'max_model_requests': 3, 'max_output_tokens': budget.max_output_tokens,
                       'turn_timeout_s': 90, 'retries': 0, 'max_request_bytes': 128*1024},
        'data_bindings': {'current': 'management-current-water@1', 'history': 'management-water-history@1',
                          'knowledge': 'management-project-knowledge@1', 'score': 'management-water-score@1',
                          'events': {'projection': ACTIVE_EVENTS_PROJECTION, 'monitoring': 'FROZEN_TURN_DEVICE',
                                     'board': 'OPTIONAL_PROCESS_APPROVED_BOUND_REPORT_DEVICE'},
                          'instance': 'EXPLICIT_READ_ONLY_SAME_INSTANCE'},
        'presentation': {'contract': PRESENTATION_CONTRACT, 'model_text': 'NATURAL_NOT_SENTENCE_VERIFIED',
                          'sources': 'ACTUAL_TURN_SOURCE_LEDGER', 'max_reply_chars': 1500},
        'run_limits': {**base['run_limits'], 'model_requests_per_turn': 3, 'tool_calls_per_turn': 2},
        'cost': {**base['cost'], 'model_requests_per_turn': 3},
        'entry_implementation': {**base['entry_implementation'],
                                 **{p: implementation_sha256(root/p) for p in paths}}}


def preparation_record(scope):
    return dict(schema_version=1, contract=CONTRACT, status='candidate', qualification_id=None,
                scope=scope, scope_sha256=_hash(scope), old_approvals_accepted=False,
                real_execution_requires='CURRENT_PROCESS_WEB_AGENT_OPERATOR_CONSENT')


class AgentManagementTurn(ContinuousManagementTurn):
    max_model_requests = 3
    request_byte_limit = 128*1024

    def __init__(self, *args, output_tokens=2048, event_board_device_id=None, **kwargs):
        if event_board_device_id is not None:
            try:
                identifier(event_board_device_id)
            except ValueError:
                raise GatewayError('INVALID_AGENT_EVENT_BOARD_DEVICE') from None
        self._event_board_device_id = event_board_device_id
        self.channel_budget = AgentChannelBudget(output_tokens)
        self.output_token_limit = output_tokens
        self._initialize_live(*args, **kwargs)

    @property
    def event_board_device_id(self):
        return self._event_board_device_id

    def history_decision(self, profile, policy, registry, authorization, snapshot, *, epoch, policy_revision):
        if type(snapshot) is not HybridHistorySnapshot:
            raise GatewayError('INVALID_HYBRID_HISTORY')
        with self.permit.owner.boundary.scope():
            self.check(); self.approval.authority.validate(self.approval)
            digest = _hash(prepared_scope(self.options, self.output_token_limit))
            snapshot.authority.validate(snapshot, digest)
            expected = (authorization.instance_id, authorization.device_id, authorization.permission_revision,
                         authorization.binding_revision, policy_revision)
            names = registry.registered_names()
            definitions={d.name:d for d in _DEFINITIONS}
            if (digest!=self.approval.scope_sha256 or profile!=assistant_profile(PRESET)
                    or type(authorization.budget) is not AgentChannelBudget or authorization.budget!=self.channel_budget
                    or not set(names)<=set(TOOLS) or tuple(policy.exposed_tools)!=names
                    or not set(names)<=set(authorization.tools)
                    or self.event_board_device_id == authorization.device_id
                    or any(registry.lookup(name).model_definition!=definitions[name] for name in names)
                    or snapshot is not self.snapshot or snapshot.authority is not self.authority
                    or snapshot.identity[3:8]!=expected or snapshot.identity[9]!=self.conversation_epoch):
                raise GatewayError('SESSION_RUN_BINDING_CHANGED')
            revision = _hash([self.approval.approval_id,digest,self.approval.bindings_sha256,epoch,
                snapshot.identity,snapshot.revision,snapshot.focus,[asdict(t) for t in snapshot.history],names,
                self.event_board_device_id])
            return ExecutionDecision(AssistantExecutionProfile(ToolExecutionMode.BOUNDED_MULTI_ROUND,
                revision,self.release_status,'MANAGEMENT_WEB_AGENT_PROCESS_CONSENT'),True,
                max_output_tokens=self.output_token_limit)

    def validate_tool_result(self, result):
        self.check()
        # Authority comes from the bound Registry/Executor and the original
        # Receipt validator. Knowledge has no simulator source_kind field.
        if type(result) is not dict:raise GatewayError('TRIAL_SOURCE_NOT_APPROVED')

    def report(self):
        report = QwenTrialSession.report(self)
        result = getattr(self, 'hybrid_result', None)
        publication = result.publication if result is not None else None
        return {**report, 'branch': result.branch if result else None,
                'tool_executions': result.tool_executions if result else 0,
                'source_kinds': list(result.source_kinds) if result else [],
                'publication_code': publication.code if publication else None,
                'presentation_valid': bool(publication and publication.allowed),
                'safe_fallback': bool(publication and publication.facts_only),
                'output_contract': PRESENTATION_CONTRACT,
                'model_text_displayed': bool(publication and publication.allowed),
                'model_text_verified': False, 'general_fact_verified': False,
                'raw_model_response_displayed': False}


@dataclass(frozen=True)
class AgentChannelResult(ChannelAssistantResult):
    branch: str = 'failed'
    model_requests: int = 0
    tool_executions: int = 0
    receipts: tuple[TurnSourceReceipt, ...] = ()
    source_notes: tuple[str, ...] = ()
    publication: object = field(default=None, repr=False)

    @property
    def source_kinds(self):
        return tuple(r.tool_name for r in self.receipts)

    def history_metadata(self):
        if not self.receipts:return (),('general','model_knowledge','NO_OBSERVATION')
        times = tuple(dict.fromkeys(t for r in self.receipts for t in
            (r.observed_at,r.evaluated_at,r.history_range_start,r.history_range_end) if t))[:3]
        aliases={CURRENT_WATER_QUALITY:'current',WATER_QUALITY_HISTORY:'history',
                 SEARCH_FISHERY_KNOWLEDGE:'knowledge',WATER_QUALITY_SCORE:'score',ACTIVE_EVENTS:'events'}
        return times,('agent',*dict.fromkeys(aliases[r.tool_name] for r in self.receipts))


def build_result(result, authorization, revision):
    from .channel_agent_presentation import source_notes
    tools = [s for s in result.execution.steps if isinstance(s, ToolExecutionStep)]
    models = sum(isinstance(s, ModelExecutionStep) for s in result.execution.steps)
    completed = result.status.value == 'completed'
    receipts = tuple(e.receipt for e in result.source_ledger.entries)
    if completed and (len(tools)>2 or models!=len(tools)+1 or models>3
            or len(receipts)!=len(tools) or any(r.tool_name not in authorization.tools for r in receipts)):
        raise GatewayError('AGENT_EXECUTION_SHAPE_INVALID')
    if completed:
        checks = {CURRENT_WATER_QUALITY: 'observation_query_completed',
                  WATER_QUALITY_SCORE: 'score_evaluation_completed',
                  SEARCH_FISHERY_KNOWLEDGE: 'project_search_completed',
                  WATER_QUALITY_HISTORY: 'history_query_completed',
                  ACTIVE_EVENTS: 'active_events_query_completed'}
        if any(not getattr(r, checks.get(r.tool_name,''),False) for r in receipts):
            raise GatewayError('AGENT_SOURCE_UNAVAILABLE')
    value = AgentChannelResult(completed,result.error_code,None,result.final_text,revision,
        branch=('tools' if tools else 'general') if completed else 'failed',model_requests=models,
        tool_executions=len(tools),receipts=receipts,
        source_notes=source_notes(tools,receipts) if completed else ())
    return replace(value,publication=present(value)) if completed else value
