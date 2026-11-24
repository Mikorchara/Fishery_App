"""Startup-approved Web event trial with its own confirmation scope."""

from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path

from apps.ai_backend.history_projection import DEFAULT_HISTORY_PROJECTION, TRANSCRIPT_NOTICE
from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.tool_conversation import ToolExecutionMode, ToolModelTransport
from apps.monitoring.contracts import identifier
from apps.monitoring.history import HISTORY_VERSION, MAX_HISTORY_ROWS, MAX_HISTORY_ITEMS, MAX_HISTORY_RESULT_BYTES
from .business_tools import active_events
from .execution import ExecutionDecision, management_scope
from .normal_selection import UNIFIED_PRESET
from .runtime.assistant import assistant_profile
from .runtime.event_notice import EventNotice, event_metric_query, requires_active_events
from .runtime.release_contracts import AssistantExecutionProfile, _hash
from .runtime.sources import HISTORY_SOURCE_CONTRACT_VERSION
from .runtime.streaming_contracts import streaming_scope
from .score_execution import SCORE_TOOL_NAMES


CONTRACT = 'management-active-event-tool-trial@1'
ACTIVE_EVENT_TOOL_NAMES = (*SCORE_TOOL_NAMES, active_events.ACTIVE_EVENTS)


_APP_ROOT = Path(__file__).resolve().parents[1]
_IMPLEMENTATION = (
    'ai_service/active_event_execution.py',
    'ai_service/business_tools/active_events.py',
    'ai_service/business_tools/registry.py',
    'ai_service/management_policy.py',
    'ai_service/runtime/assistant.py',
    'ai_service/runtime/event_notice.py',
    'ai_service/runtime/history_selection.py',
    'ai_service/runtime/history_summary.py',
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
    'ai_backend/tool_conversation.py',
    'ai_backend/tools/contracts.py',
)


def event_notice_for_turn(question, policy, access):
    """Project an event denial only for an explicit event request in this turn."""
    if policy.allows(active_events.ACTIVE_EVENTS) or not isinstance(question, str):
        return None
    if requires_active_events(question):
        return EventNotice(access)
    metric = event_metric_query(question)
    return EventNotice(access, metric) if metric is not None else None


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
