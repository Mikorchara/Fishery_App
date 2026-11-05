"""Management-only experimental capability. Not a promotion of M2 candidates."""
from dataclasses import dataclass
import os
from pathlib import Path
import time

import httpx
from openai import AsyncOpenAI
from apps.ai_backend.model_gateway import GatewayError
from .channel_hybrid import HybridQwenTurn, HybridHistorySnapshot, prepared_scope as offline_scope
from .channel_session_run import TurnLease, memory_sdk_factory
from .channel_trial import QwenTrialSession, PRESET, MAX_REQUEST_BYTES
from .channel_validation import implementation_sha256
from .runtime.assistant import assistant_profile
from .runtime.release_contracts import _hash
from .channel_hybrid import INSTRUCTION as HYBRID_INSTRUCTION
from .management_channel_budget import CHANNEL_BUDGET, OUTPUT_TOKENS, reservation_per_turn

CONTRACT = 'management-qq-hybrid-process-run@1'
PROMPT_ID = 'QQ_MANAGEMENT_HYBRID_DIALOGUE@5'
INSTRUCTION = HYBRID_INSTRUCTION + (
    '工具调用示例：调用get_current_water_quality()，没有任何形参。'
    '传给函数的JSON参数对象必须恰好是{}，不能再包一层arguments或parameters，不能添加空字段。'
    '合法工具调用格式示例：{"name":"get_current_water_quality","arguments":"{}"}。'
    '不要传入device_id、问题、指标或任何其他字段，设备已由服务器绑定。'
    'Tool返回后不要复述整个报文，不输出长篇报告或推理过程；仅返回规定的water plan JSON。'
    'general仅简短中文，water仅选择指标ID、已有规则code与建议code，不新增事实数值。')


def prepared_scope(options):
    root = Path(__file__).resolve().parents[2]
    base = offline_scope(options)
    paths = ('apps/qq_bot/event_notifications.py', 'apps/qq_bot/event_recipients.py',
             'apps/ai_service/channel_management_live.py', 'apps/qq_bot/management_run.py',
             'apps/qq_bot/management_config.py', 'apps/qq_bot/management_cli.py',
             'apps/qq_bot/live_transport.py', 'apps/qq_bot/demo_runtime.py',
             'apps/management_process.py', 'apps/management_web/__main__.py',
             'apps/ai_service/management_channel_budget.py', 'apps/qq_bot/management_limits.py',
             'apps/monitoring/device_events.py','apps/device_reports/bridge.py','apps/device_reports/storage.py',
             'apps/monitoring/event_reset.py')
    # Runtime authorization remains enforceable from an installed Wheel without
    # source-only PowerShell scripts. Distribution launchers have a separate
    # allowlist/manifest and cannot mint a permit or bypass the CLI approval.
    return {**base, 'contract': CONTRACT, 'environment': 'EXPLICIT_MANAGEMENT_EXPERIMENT',
            'runtime':{**base['runtime'],'prompt_id':PROMPT_ID,'prompt_sha256':_hash(INSTRUCTION)},
            'execution':{**base['execution'],'max_output_tokens':OUTPUT_TOKENS},
            'process':{**base['process'],'max_seconds':28800,'max_turns':None,
                       'turn_bound':'EXPLICIT_CAP_OR_FLOOR_APPROVED_BUDGET_DIV_RESERVATION',
                       'max_budget_cny':'2000'},
            'cost':{**base['cost'],'output_tokens_per_request':OUTPUT_TOKENS,
                    'reservation_cny':str(reservation_per_turn()),'reservation_per_turn_cny':str(reservation_per_turn())},
            'approval': 'PROCESS_NONCE_OPERATOR_RUNCONSENT_GENERAL_RISK@1',
            'run_limits': {'contract':'management-budget-bounded-run@1','optional_turn_cap':True,
                           'max_seconds':28800,'max_budget_cny':'2000','refund':False},
            'failure_notice':'TWO_FIXED_ERRORS_PASSIVE_ONCE_NO_HISTORY@1',
            'publication': 'OPERATOR_APPROVED_GENERAL_RESIDUAL_RISK',
            'websocket_dependency': 'websockets==15.0.1',
            'entry_implementation': {p: implementation_sha256(root/p) for p in paths}}


def preparation_record(scope):
    return dict(schema_version=1, contract=CONTRACT, status='candidate', qualification_id=None,
                scope=scope, scope_sha256=_hash(scope), old_approvals_accepted=False,
                real_execution_requires='CURRENT_PROCESS_OPERATOR_RUNCONSENT')


@dataclass(frozen=True, repr=False)
class LivePermit:
    owner: object
    nonce: object
    scope_sha256: str
    bindings_sha256: str
    consent_id: str
    lease_authority: object
    offline: bool

    def check(self):
        self.owner.validate(self)


class LivePermitIssuer:
    def __init__(self, check):
        self._check, self._pid, self._value = check, os.getpid(), None

    def issue(self, **fields):
        if self._value is not None:
            raise GatewayError('MANAGEMENT_RUN_ALREADY_APPROVED')
        self._value = LivePermit(self, object(), **fields)
        return self._value

    def validate(self, value):
        if type(value) is not LivePermit or value is not self._value or value.owner is not self or self._pid != os.getpid():
            raise GatewayError('MANAGEMENT_RUN_PERMIT_REQUIRED')
        self._check()


class ManagementLiveTurn(HybridQwenTurn):
    release_status = 'local_experimental'
    output_token_limit = OUTPUT_TOKENS
    channel_budget = CHANNEL_BUDGET

    def __init__(self, lease, *, permit, authority, conversation_epoch, options, snapshot,
                 validate, claim, async_client_factory=None, clock=None, monotonic=time.monotonic):
        self._initialize_live(lease, permit=permit, authority=authority,
            conversation_epoch=conversation_epoch, options=options, snapshot=snapshot,
            validate=validate, claim=claim, async_client_factory=async_client_factory,
            clock=clock, monotonic=monotonic)

    def _initialize_live(self, lease, *, permit, authority, conversation_epoch, options, snapshot,
                         validate, claim, async_client_factory=None, clock=None, monotonic=time.monotonic):
        # Shared SDK ownership only. Public constructors select their own exact
        # budget/Scope contract before entering this guarded initialization.
        if type(permit) is not LivePermit or type(lease) is not TurnLease:
            raise GatewayError('MANAGEMENT_RUN_PERMIT_REQUIRED')
        permit.check(); lease.authority.validate(lease)
        if (lease.authority is not permit.lease_authority or lease.scope_sha256 != permit.scope_sha256
                or lease.bindings_sha256 != permit.bindings_sha256
                or not lease.approval_id.startswith(permit.consent_id+'-')
                or snapshot.identity[:5] != (lease.app_id, lease.group_id, lease.member_id, lease.instance_id, lease.device_id)
                or permit.offline != (async_client_factory is not None)):
            raise GatewayError('MANAGEMENT_RUN_LEASE_MISMATCH')
        self.permit, self.authority = permit, authority
        self.conversation_epoch, self.options, self.snapshot = conversation_epoch, options, snapshot

        def guarded_validate():
            permit.check(); validate()

        def sdk_factory(runtime, remaining):
            permit.check()
            profile = assistant_profile(PRESET)
            if runtime.base_url != profile.base_url or runtime.model != profile.model:
                raise GatewayError('MANAGEMENT_PROVIDER_BINDING_CHANGED')
            attempts = 0

            async def before_request(request):
                nonlocal attempts
                self.check(); self.handle.check()
                if (attempts or request.method != 'POST'
                        or str(request.url) != runtime.base_url.rstrip('/')+'/chat/completions'
                        or len(request.content) > MAX_REQUEST_BYTES):
                    raise GatewayError('MANAGEMENT_PROVIDER_REQUEST_REJECTED')
                attempts += 1
                with self._lock:
                    if self.http_requests >= 2:
                        raise GatewayError('TRIAL_MODEL_REQUEST_LIMIT')
                    self.http_requests += 1

            if permit.offline:
                client = async_client_factory(runtime, remaining)
                owner = memory_sdk_factory(lambda *_: client)(runtime, remaining)
                _ = owner.chat  # Validate exact SDK, MockTransport, retries/proxy policy before I/O.
                client._client.event_hooks['request'].append(before_request)
                return owner
            timeout = httpx.Timeout(connect=min(runtime.connect_timeout_s, remaining),
                read=min(runtime.read_timeout_s, remaining), write=min(runtime.read_timeout_s, remaining),
                pool=min(runtime.connect_timeout_s, remaining))
            http = httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False,
                                     event_hooks={'request': [before_request]})
            class OwnedClient:
                client = None
                @property
                def chat(owner):
                    if owner.client is None:
                        owner.client = AsyncOpenAI(api_key=runtime.credential._for_adapter(),
                            base_url=runtime.base_url, max_retries=0, timeout=timeout, http_client=http)
                    return owner.client.chat
                async def close(owner):
                    if owner.client is not None: await owner.client.close()
                    else: await http.aclose()
                def is_closed(owner):
                    return http.is_closed and (owner.client is None or owner.client.is_closed())
            return OwnedClient()

        self._initialize(lease, validate=guarded_validate, claim=claim,
            async_client_factory=sdk_factory, clock=clock, monotonic=monotonic)
        self.offline_test = permit.offline

    def check(self):
        with self.permit.owner.boundary.scope():
            return QwenTrialSession.check(self)

    def history_decision(self, profile, policy, registry, authorization, snapshot, *, epoch, policy_revision):
        if type(snapshot) is not HybridHistorySnapshot:
            raise GatewayError('INVALID_HYBRID_HISTORY')
        with self.permit.owner.boundary.scope():
            self.check(); self.approval.authority.validate(self.approval)
            return self._bound_history_decision(profile, policy, registry, authorization, snapshot,
                epoch=epoch, policy_revision=policy_revision,
                digest=_hash(prepared_scope(self.options)), reason='MANAGEMENT_EXPLICIT_PROCESS_RUNCONSENT')
