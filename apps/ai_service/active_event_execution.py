"""Startup-approved Web event trial with its own confirmation scope."""

from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path
import re

from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION, TRANSCRIPT_NOTICE
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolExecutionMode, ToolModelTransport
from apps.monitoring.contracts import identifier
from apps.monitoring.history import HISTORY_VERSION, MAX_HISTORY_ROWS, MAX_HISTORY_ITEMS, MAX_HISTORY_RESULT_BYTES
from .business_tools import active_events
from .execution import ExecutionDecision, management_scope
from .normal_selection import UNIFIED_PRESET
from .runtime.assistant import MULTI_ROUND_SYSTEM_INSTRUCTION, assistant_profile
from .runtime.release_contracts import AssistantExecutionProfile, _hash
from .runtime.sources import HISTORY_SOURCE_CONTRACT_VERSION
from .runtime.streaming_contracts import streaming_scope
from .score_execution import SCORE_TOOL_NAMES


CONTRACT = 'management-active-event-tool-trial@1'
ACTIVE_EVENT_TOOL_NAMES = (*SCORE_TOOL_NAMES, active_events.ACTIVE_EVENTS)
ACTIVE_EVENT_PROMPT = (
    'ASSISTANT_ACTIVE_EVENTS@1',
    MULTI_ROUND_SYSTEM_INSTRUCTION
    + '用户明确询问当前有哪些事件、异常或告警时，使用已授权的 get_active_events，参数固定为空对象。'
    '依据本轮实际返回的事件来源、状态和时间说明结果，区分 SIMULATOR 模拟记录和设备报告。'
    '保留待核实、待复核、观测缺失、过期和结果截断等限制。'
    '未查到符合条件的事件只适用于已查询范围，不能证明鱼群健康或风险已经消退。'
    '设备报告中断只描述报告更新，不能证明设备离线。'
    '外观和行为信号需要人工核查，不能用来确诊疾病。'
    '没有本轮事件查询依据时，说明当前事件无法核实。工具不会确认、删除、结束事件或操作设备。',
)

_EVENT_NOUN = r'(?:(?:(?:还在|正在)发生的|未结束的)?事件|活动事件|活跃事件|异常事件|告警|异常)'
_CURRENT = r'(?:当前|现在|目前)'
_CURRENT_EVENT_QUESTION = re.compile(
    rf'(?:请问|帮我看看|帮我查一下)?{_CURRENT}(?:鱼塘|养殖池|设备)?(?:还)?'
    rf'(?:有什么|有哪些|是否有|有没有|有无|有){_EVENT_NOUN}(?:还没有结束|还在发生|吗)?'
    rf'|(?:请问)?{_CURRENT}(?:的)?{_EVENT_NOUN}(?:有哪些|有什么)'
    rf'|(?:请|帮我)?(?:查看|查询|检查|查一下|看看){_CURRENT}(?:的)?{_EVENT_NOUN}'
    rf'|{_CURRENT}(?:还在|正在)发生的事件'
    rf'|(?:请问)?{_CURRENT}发生(?:了)?(?:什么|哪些)事件(?:了)?(?:吗)?'
)

_APP_ROOT = Path(__file__).resolve().parents[1]
_IMPLEMENTATION = (
    'ai_service/active_event_execution.py',
    'ai_service/business_tools/active_events.py',
    'ai_service/business_tools/registry.py',
    'ai_service/management_policy.py',
    'ai_service/runtime/assistant.py',
    'ai_service/runtime/sources.py',
    'ai_service/service.py',
    'monitoring/device_events.py',
    'monitoring/event_cycles.py',
    'monitoring/event_families.py',
    'monitoring/manual_end.py',
    'monitoring/repository.py',
    'monitoring/service.py',
    'management_web/streaming.py',
    'ai_backend/assistant_events.py',
)


def requires_active_events(question):
    """Recognize explicit current event queries for the mandatory source gate."""
    return isinstance(question, str) and bool(
        _CURRENT_EVENT_QUESTION.fullmatch(question.strip().rstrip('？?。！!').rstrip())
    )


def _implementation():
    try:
        return tuple((name, hashlib.sha256((_APP_ROOT / name).read_bytes()).hexdigest())
                     for name in _IMPLEMENTATION)
    except OSError:
        raise GatewayError('INVALID_ACTIVE_EVENT_TRIAL_CONFIG') from None


@dataclass(frozen=True)
class ActiveEventTrialConfig:
    enabled: bool = False
    device_report_device_id: str | None = None
    implementation: tuple[tuple[str, str], ...] = field(init=False, repr=False, default=())

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise GatewayError('INVALID_ACTIVE_EVENT_TRIAL_CONFIG')
        if self.device_report_device_id is not None:
            try:
                identifier(self.device_report_device_id)
            except ValueError:
                raise GatewayError('INVALID_ACTIVE_EVENT_TRIAL_CONFIG') from None
            if not self.enabled:
                raise GatewayError('INVALID_ACTIVE_EVENT_TRIAL_CONFIG')
        if self.enabled:
            object.__setattr__(self, 'implementation', _implementation())


def active_event_scope(profile, policy, registry, knowledge, transport, *, device_report_device_id=None):
    """Bind the exact exposed definitions and source selection to the turn revision."""
    scope = management_scope(profile, policy, registry, knowledge)
    streaming = transport == ToolModelTransport.STREAMING
    if streaming:
        scope['runtime'] = streaming_scope(profile, policy, registry, DEFAULT_HISTORY_PROJECTION)
    prompt_id, instruction = ACTIVE_EVENT_PROMPT
    scope['runtime'].update(prompt_id=prompt_id, prompt_sha256=_hash(instruction))
    return {
        **scope, 'contract': CONTRACT, 'transport': transport.value,
        'generation': asdict(profile.default_generation),
        'history_framing_sha256': _hash(TRANSCRIPT_NOTICE),
        'history_binding': {
            'version': HISTORY_VERSION, 'device': 'FROZEN_PER_TURN',
            'max_rows': MAX_HISTORY_ROWS, 'max_items': MAX_HISTORY_ITEMS,
            'max_result_bytes': MAX_HISTORY_RESULT_BYTES, 'source_version': HISTORY_SOURCE_CONTRACT_VERSION,
        },
        'event_binding': {
            'projection': active_events.ACTIVE_EVENTS_PROJECTION,
            'device': 'FROZEN_PER_TURN', 'device_report_device_id': device_report_device_id,
            'max_items': active_events.MAX_ACTIVE_EVENT_ITEMS,
            'max_cycles': active_events.MAX_ACTIVE_EVENT_CYCLES,
            'max_result_bytes': active_events.MAX_ACTIVE_EVENT_RESULT_BYTES,
        },
        'implementation': dict(_implementation()),
        'budget': {
            'calls': 2, 'rounds': 2, 'requests': 3, 'retry': profile.max_retries,
            'deadline_s': profile.total_timeout_s, 'max_output_tokens': 512 if streaming else 1024,
        },
    }


def resolve_active_event_trial(config, profile, policy, registry, knowledge, *,
                               device_id, epoch, policy_revision, transport):
    scope = active_event_scope(profile, policy, registry, knowledge, transport,
                               device_report_device_id=config.device_report_device_id)
    definitions = policy.model_definitions(registry)
    matched = (
        type(transport) is ToolModelTransport
        and profile == assistant_profile(UNIFIED_PRESET)
        and policy.mode == 'assistant'
        and active_events.ACTIVE_EVENTS_DEFINITION in definitions
        and set(scope['runtime']['tools']) == set(policy.exposed_tools) <= set(ACTIVE_EVENT_TOOL_NAMES)
        and scope['implementation'] == dict(config.implementation)
        and config.device_report_device_id != device_id
    )
    can_send = config.enabled and matched
    reason = 'active' if can_send else 'flag_disabled' if not config.enabled else 'scope_not_published'
    revision = _hash({
        'trial': CONTRACT, 'scope': scope, 'enabled': config.enabled,
        'device': device_id, 'epoch': epoch, 'policy_revision': policy_revision,
    })
    return ExecutionDecision(
        AssistantExecutionProfile(ToolExecutionMode.BOUNDED_MULTI_ROUND, revision, 'local_experimental', reason),
        can_send, transport, scope['budget']['max_output_tokens'],
    )
