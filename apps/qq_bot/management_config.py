"""Explicit Management config; Check never opens SQLite, credentials or network."""
from dataclasses import dataclass, asdict
from decimal import Decimal
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import json

from apps.ai_service.channel_management_live import prepared_scope, preparation_record, CONTRACT
from apps.ai_service.channel_trial import PRESET
from apps.ai_service.management_channel_budget import CHANNEL_BUDGET, OUTPUT_TOKENS, reservation_per_turn
from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.runtime.release_contracts import _hash
from .conversations import ConversationOptions
from .contracts import BotError
from .management_limits import ManagementRunLimits as RunLimits
from .trial_configuration import TrialInputs, inputs_snapshot as trial_inputs_snapshot, local_path, read_json
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]
PREPARATION = ROOT/'apps/ai_service/resources/management_qq_hybrid_live_preparation.json'
from apps.management_process import ISOLATED_MARKER_CONTRACT as MARKER
RISK = ('普通自然语言可能收费；General 不是现场核验或专业保证。SIMULATOR 及必要历史将披露给 Qwen 和 QQ。'
        '失败/超时/未知送达不退款、不重试。本地预算不是云账单硬上限；不合作 SDK 线程可能无法强制退出，远端计费未知。')


def inputs_snapshot(inputs,monitoring=None,*,budget=None):
    if budget is None:
        from .ai_configuration import load_ai_config
        budget=load_ai_config(inputs.ai_config).budget
    from apps.ai_service.channel_management_continuous import ContinuousChannelBudget
    from apps.ai_service.channel_management_agent import AgentChannelBudget
    return trial_inputs_snapshot(inputs,monitoring,expected_budget=budget,
        allow_disabled=type(budget) in (ContinuousChannelBudget,AgentChannelBudget))


def ensure_private_directory(path):
    from apps.ai_backend.secure_files import private_directory, inspect_policy, SecureFileError
    if not path.exists():
        try:private_directory(path)
        except SecureFileError:
            if not path.is_dir():raise
    inspect_policy(path,directory=True)


@contextmanager
def process_lock(path):
    from apps.ai_backend.secure_files import exclusive_lock, FileBusyError
    try:
        with exclusive_lock(path):yield
    except FileBusyError:raise BotError('MANAGEMENT_INSTANCE_OR_BOT_ALREADY_RUNNING') from None


@dataclass(frozen=True)
class ManagementRequest:
    path: Path
    inputs: TrialInputs
    limits: RunLimits
    members: tuple
    scope_sha256: str
    enabled: bool
    digest: str
    event_recipient_file: Path | None = None
    output_tokens: int = OUTPUT_TOKENS
    ai_enabled: bool = True
    agent_mode: str = 'current'

    @property
    def continuous(self):return self.limits.continuous

    @property
    def web_agent(self):return self.agent_mode=='web'

    def check(self):
        if _hash(read_json(self.path)) != self.digest:
            raise BotError('MANAGEMENT_REQUEST_CHANGED')


def load_request(path):
    path = local_path(path)
    value = read_json(path)
    required = {'schema_version', 'enabled', 'inputs', 'limits', 'members', 'scope_sha256'}
    if value.get('schema_version') in (2,3):required.add('ai_enabled')
    if value.get('schema_version')==3:required.add('agent_mode')
    optional={'event_recipient_file'}|({'verified_recipient_file'} if value.get('schema_version') in (2,3) else set())
    if (not required<=set(value) or set(value)-required-optional
            or type(value['schema_version']) is not int or value['schema_version'] not in (1,2,3)
            or type(value['enabled']) is not bool or type(value.get('ai_enabled',True)) is not bool or type(value['members']) is not list
            or not 1 <= len(value['members']) <= 4):
        raise BotError('INVALID_MANAGEMENT_REQUEST')
    inputs = TrialInputs.parse(value['inputs'])
    raw_limits=dict(value['limits'])
    reported_budget_only=raw_limits.pop('budget_only',None)
    limits = RunLimits(**raw_limits)
    if reported_budget_only is not None and reported_budget_only is not limits.budget_only:
        raise BotError('INVALID_MANAGEMENT_REQUEST')
    web_agent=value['schema_version']==3
    if web_agent and value['agent_mode']!='web':raise BotError('INVALID_MANAGEMENT_REQUEST')
    if limits.continuous!=(value['schema_version'] in (2,3)):raise BotError('INVALID_MANAGEMENT_REQUEST')
    from .gateway import validate_run_duration
    if not limits.continuous:validate_run_duration(limits.seconds,max_seconds=limits.seconds)
    if not limits.continuous and Decimal(limits.total_budget_cny)<reservation_per_turn()*limits.max_turns:
        raise BotError('RUN_BUDGET_INSUFFICIENT')
    access, ai, source, grant, _ = inputs_snapshot(inputs)
    if limits.continuous:
        from apps.ai_service.channel_management_continuous import ContinuousChannelBudget
        from apps.ai_service.channel_management_agent import AgentChannelBudget
        expected_type=AgentChannelBudget if web_agent else ContinuousChannelBudget
        if type(ai.budget) is not expected_type:raise BotError('INVALID_CONTINUOUS_CHANNEL_BUDGET')
    elif ai.budget!=CHANNEL_BUDGET or type(ai.budget) is not type(CHANNEL_BUDGET):
        raise BotError('INVALID_MANAGEMENT_CHANNEL_BUDGET')
    selected = tuple(value['members'])
    group = next(g for g in access.groups if g.group_id == inputs.group_id)
    if (len(set(selected)) != len(selected) or inputs.member_id not in selected
            or any(m not in group.members or m not in grant.members for m in selected)):
        raise BotError('RUN_MEMBERS_NOT_APPROVED')
    # First M3 release intentionally cannot select the formal or existing demo root.
    root = source.data_root.resolve()
    if not root.is_relative_to(ROOT/'outputs') or root == ROOT/'outputs/demo-instance':
        raise BotError('SEPARATE_REAL_INSTANCE_APPROVAL_REQUIRED')
    marker = read_json(root/'qq-isolated-instance.json')
    if marker != {'contract': MARKER, 'root': str(root), 'instance_id': source.instance_id,
                  'device_id': grant.device_id, 'source': 'SIMULATOR'}:
        raise BotError('ISOLATED_INSTANCE_PROOF_REQUIRED')
    # Metadata only; actual v2/schema/integrity is rechecked RO by InstanceMonitoring at Run.
    for name in ('monitoring.sqlite3', 'knowledge.sqlite3'):
        p = local_path(root/name)
        if not p.is_file() or p.stat().st_size == 0:
            raise BotError('MANAGEMENT_INSTANCE_MISSING')
    options=ConversationOptions(trigger_mode='mention_ai', memory_enabled=True)
    if limits.continuous:
        if web_agent:
            from apps.ai_service.channel_management_agent import prepared_scope as continuous_scope,preparation_record as continuous_record
        else:
            from apps.ai_service.channel_management_continuous import prepared_scope as continuous_scope,preparation_record as continuous_record
        scope=continuous_scope(options,output_tokens=ai.budget.max_output_tokens)
        record=continuous_record(scope);record_path=path.parent/'scope.json'
    else:scope=prepared_scope(options);record=preparation_record(scope);record_path=PREPARATION
    if read_json(record_path) != record or value['scope_sha256'] != _hash(scope):
        raise BotError('MANAGEMENT_SCOPE_REVIEW_REQUIRED')
    recipient_path = local_path(value['event_recipient_file']) if 'event_recipient_file' in value else None
    if 'verified_recipient_file' in value:
        from .event_recipients import load_recipient
        load_recipient(local_path(value['verified_recipient_file']),access.app_id)
    if recipient_path:
        from .event_recipients import load_recipient
        load_recipient(recipient_path,access.app_id)
    if limits.continuous and value['ai_enabled'] is not ai.enabled:raise BotError('MANAGEMENT_AI_SWITCH_MISMATCH')
    return ManagementRequest(path, inputs, limits, selected, _hash(scope), value['enabled'], _hash(value),recipient_path,
        ai.budget.max_output_tokens,value.get('ai_enabled',value['enabled']),'web' if web_agent else 'current')


def check_request(path, *, offline=False, device_report_device_id=None):
    request = load_request(path)
    if not offline:
        try:
            if version('websockets') != '15.0.1': raise PackageNotFoundError()
        except PackageNotFoundError:
            raise BotError('QQ_WEBSOCKETS_15_0_1_REQUIRED') from None
    profile = assistant_profile(PRESET)
    source = read_json(request.inputs.monitoring_config)
    from apps.ai_service.channel_management_continuous import CONTRACT as CONTINUOUS_CONTRACT
    from apps.ai_service.channel_management_agent import CONTRACT as AGENT_CONTRACT
    selected_access,selected_ai,*_=inputs_snapshot(request.inputs)
    tools=next(g.tools for g in selected_ai.grants if g.group_id==request.inputs.group_id)
    return request, dict(code='MANAGEMENT_QQ_CHECKED_APPROVAL_REQUIRED', contract=AGENT_CONTRACT if request.web_agent else CONTINUOUS_CONTRACT if request.continuous else CONTRACT,
        enabled=request.enabled, ai_enabled=request.ai_enabled, provider=profile.service_id, model=profile.model, preset=PRESET,
        agent_mode=request.agent_mode,tools=list(tools),max_model_requests_per_turn=3 if request.web_agent else 2,
        scope_sha256=request.scope_sha256, data_root=source['data_root'], instance_id=source['instance_id'],
        device_id=next(g.device_id for g in inputs_snapshot(request.inputs)[0].groups if g.group_id == request.inputs.group_id),
        group_ref=_hash(request.inputs.group_id)[:12], member_refs=[_hash(m)[:12] for m in request.members],
        limits=asdict(request.limits), reservation_per_turn_cny=None if request.continuous else str(reservation_per_turn()),
        max_model_requests=None if request.continuous else request.limits.max_turns*2, output_tokens_per_request=request.output_tokens,
        seconds_per_turn=90, retries=0, offline=offline, credential_checked=False,
        database_opened=False, network_requests=0,
        risk=(CONTINUOUS_RISK+('本轮选用的项目知识、历史统计及必要上下文可能披露给Qwen和QQ；'
              '最多2次只读工具、3次模型请求，不是专业保证。' if request.web_agent else '') if request.continuous else RISK),
        event_notifications=check_event_recipient(request,device_report_device_id))


CONTINUOUS_RISK=('本进程持续运行，不按累计时长、轮数或费用停止。普通自然语言可能持续产生模型费用，'
    '直到人工停止、撤权或严重故障；模型一般回答不是现场核验或专业保证。'
    '每轮仍有超时、只读权限和SDK资源检查；送达未知不重试，退出不恢复旧任务。')


def check_event_recipient(request,device_report_device_id=None):
    # Explicit request binding; other instances never inherit a global destination.
    path=request.event_recipient_file
    if path is None:return None
    from .event_recipients import load_recipient
    from .event_notifications import approval_summary
    access=inputs_snapshot(request.inputs)[0]
    if device_report_device_id is not None:
        from .contracts import identifier
        identifier(device_report_device_id)
        water=next(g.device_id for g in access.groups if g.group_id==request.inputs.group_id)
        if device_report_device_id==water:raise BotError('DEVICE_EVENT_SOURCE_CONFLICT')
    return approval_summary(load_recipient(path,access.app_id),device_report_device_id)
