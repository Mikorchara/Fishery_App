"""Explicit Management config; Check never opens SQLite, credentials or network."""
from dataclasses import dataclass, asdict
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import json

from apps.ai_service.channel_management_live import prepared_scope, preparation_record, CONTRACT
from apps.ai_service.channel_trial import PRESET, cost_reservation
from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.runtime.release_contracts import _hash
from .conversations import ConversationOptions
from .contracts import BotError
from .run_consent import RunLimits
from .trial_configuration import TrialInputs, inputs_snapshot, local_path, read_json
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]
PREPARATION = ROOT/'apps/ai_service/resources/management_qq_hybrid_live_preparation.json'
from apps.management_process import ISOLATED_MARKER_CONTRACT as MARKER
RISK = ('普通自然语言可能收费；General 不是现场核验或专业保证。SIMULATOR 及必要历史将披露给 Qwen 和 QQ。'
        '失败/超时/未知送达不退款、不重试。本地预算不是云账单硬上限；不合作 SDK 线程可能无法强制退出，远端计费未知。')


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

    def check(self):
        if _hash(read_json(self.path)) != self.digest:
            raise BotError('MANAGEMENT_REQUEST_CHANGED')


def load_request(path):
    path = local_path(path)
    value = read_json(path)
    required = {'schema_version', 'enabled', 'inputs', 'limits', 'members', 'scope_sha256'}
    if (set(value) not in (required, required | {'event_recipient_file'})
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or type(value['enabled']) is not bool or type(value['members']) is not list
            or not 1 <= len(value['members']) <= 4):
        raise BotError('INVALID_MANAGEMENT_REQUEST')
    inputs = TrialInputs.parse(value['inputs'])
    limits = RunLimits(**value['limits'])
    access, ai, source, grant, _ = inputs_snapshot(inputs)
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
    scope = prepared_scope(ConversationOptions(trigger_mode='mention_ai', memory_enabled=True))
    if read_json(PREPARATION) != preparation_record(scope) or value['scope_sha256'] != _hash(scope):
        raise BotError('MANAGEMENT_SCOPE_REVIEW_REQUIRED')
    recipient_path = local_path(value['event_recipient_file']) if 'event_recipient_file' in value else None
    if recipient_path:
        from .event_recipients import load_recipient
        load_recipient(recipient_path,access.app_id)
    return ManagementRequest(path, inputs, limits, selected, _hash(scope), value['enabled'], _hash(value),recipient_path)


def check_request(path, *, offline=False):
    request = load_request(path)
    if not offline:
        try:
            if version('websockets') != '15.0.1': raise PackageNotFoundError()
        except PackageNotFoundError:
            raise BotError('QQ_WEBSOCKETS_15_0_1_REQUIRED') from None
    profile = assistant_profile(PRESET)
    source = read_json(request.inputs.monitoring_config)
    return request, dict(code='MANAGEMENT_QQ_CHECKED_APPROVAL_REQUIRED', contract=CONTRACT,
        enabled=request.enabled, provider=profile.service_id, model=profile.model, preset=PRESET,
        scope_sha256=request.scope_sha256, data_root=source['data_root'], instance_id=source['instance_id'],
        device_id=next(g.device_id for g in inputs_snapshot(request.inputs)[0].groups if g.group_id == request.inputs.group_id),
        group_ref=_hash(request.inputs.group_id)[:12], member_refs=[_hash(m)[:12] for m in request.members],
        limits=asdict(request.limits), reservation_per_turn_cny=str(cost_reservation()),
        max_model_requests=request.limits.max_turns*2, output_tokens_per_request=512,
        seconds_per_turn=90, retries=0, offline=offline, credential_checked=False,
        database_opened=False, network_requests=0, risk=RISK,
        event_notifications=check_event_recipient(request))


def check_event_recipient(request):
    # Explicit request binding; other instances never inherit a global destination.
    path=request.event_recipient_file
    if path is None:return None
    from .event_recipients import load_recipient
    from .event_notifications import approval_summary
    return approval_summary(load_recipient(path,inputs_snapshot(request.inputs)[0].app_id))
