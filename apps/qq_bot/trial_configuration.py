"""Local operator plans and one-use approvals; never accepts configuration from QQ."""
from dataclasses import asdict,dataclass
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
import threading
from pathlib import Path
import uuid

from apps.ai_backend.model_gateway import GatewayError
from apps.ai_backend.secure_files import guard_path
from apps.ai_backend.tools import ToolDefinition,ToolRegistry
from apps.ai_backend.tools.policy import ToolPolicy
from apps.ai_service.business_tools.current_water_quality import WATER_DEFINITION,CURRENT_WATER_QUALITY
from apps.ai_service.channel import ChannelBudget
from apps.ai_service.channel_trial import (QwenTrialApproval,TRIAL_CONTRACT,PRESET,PRICE_URL,
    cost_reservation,fast_trial_scope,money)
from apps.ai_service.channel_presentation import EXPLANATION_CONTRACT
from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.runtime.release_contracts import _hash
from apps.ai_service.runtime.policy import UserToolPolicyStore
from apps.ai_service.management_policy import ManagementToolPolicyStore
from .ai_configuration import load_ai_config
from .configuration import json_object,load_access
from .contracts import BotError,identifier
from .monitoring_source import InstanceMonitoring,load_monitoring_config


def local_path(value):
    path=Path(value)
    if not path.is_absolute() or path.anchor.startswith(('\\\\','//')) or '..' in path.parts:
        raise BotError('TRIAL_LOCAL_ABSOLUTE_PATH_REQUIRED')
    if os.name=='nt':
        import ctypes
        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor))!=3:
            raise BotError('TRIAL_LOCAL_DISK_REQUIRED')
    guard_path(path)
    return path


def read_json(path):
    path=local_path(path);guard_path(path,regular=True)
    try:
        with path.open('rb') as stream:return json_object(stream.read(65537),65536)
    except BotError:raise
    except Exception:raise BotError('TRIAL_RECORD_UNAVAILABLE') from None


def write_new(path,value):
    path=local_path(path);guard_path(path,regular=True)
    # Parent must already exist. Never repair, replace, merge or truncate a file.
    try:
        with path.open('x',encoding='utf-8',newline='\n') as stream:
            json.dump(value,stream,ensure_ascii=False,allow_nan=False,indent=2)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
    except FileExistsError:raise BotError('TRIAL_OUTPUT_EXISTS') from None


def scope():
    registry=ToolRegistry((ToolDefinition(WATER_DEFINITION,lambda:None),))
    policy=ToolPolicy('assistant',True,(CURRENT_WATER_QUALITY,))
    return fast_trial_scope(assistant_profile(PRESET),policy,registry)


@dataclass(frozen=True,repr=False)
class TrialInputs:
    access_file: Path
    monitoring_config: Path
    ai_config: Path
    policy_directory: Path
    group_id: str
    member_id: str

    def dictionary(self):
        return {k:str(v) for k,v in asdict(self).items()}

    @classmethod
    def parse(cls,value):
        if not isinstance(value,dict) or set(value)!={'access_file','monitoring_config','ai_config',
                'policy_directory','group_id','member_id'}:raise BotError('INVALID_TRIAL_INPUTS')
        return cls(*(local_path(value[k]) for k in ('access_file','monitoring_config','ai_config','policy_directory')),
            identifier(value['group_id']),identifier(value['member_id']))


def inputs_snapshot(inputs,monitoring=None,*,expected_budget=ChannelBudget(),allow_disabled=False):
    access=load_access(inputs.access_file);ai=load_ai_config(inputs.ai_config)
    source_config=load_monitoring_config(inputs.monitoring_config);source_config.check_bindings(access)
    if type(allow_disabled) is not bool:raise BotError('INVALID_TRIAL_CONFIGURATION')
    if not ai.enabled and not allow_disabled:raise BotError('AI_DISABLED')
    if ai.budget!=expected_budget:raise BotError('TRIAL_FIXED_BUDGET_REQUIRED')
    group=next((g for g in access.groups if g.group_id==inputs.group_id),None)
    grant=next((g for g in ai.grants if g.group_id==inputs.group_id),None)
    if (group is None or grant is None or inputs.member_id not in group.members
            or inputs.member_id not in grant.members or group.device_id!=grant.device_id
            or 'current' not in group.capabilities or grant.device_id not in source_config.devices):
        raise BotError('TRIAL_MEMBER_NOT_APPROVED')
    registry=ToolRegistry((ToolDefinition(WATER_DEFINITION,lambda:None),))
    shared=UserToolPolicyStore(inputs.policy_directory,registry)
    policy=ManagementToolPolicyStore(inputs.policy_directory,shared).snapshot()
    if CURRENT_WATER_QUALITY not in policy.selected_tools:raise BotError('CHANNEL_TOOL_NOT_AUTHORIZED')
    if monitoring is not None and monitoring.config!=source_config:raise BotError('TRIAL_BINDINGS_CHANGED')
    bindings=dict(inputs=inputs.dictionary(),access=asdict(access),ai=asdict(ai),
        source={'instance_id':source_config.instance_id,'root':str(source_config.data_root),
                'devices':source_config.devices},policy_revision=policy.revision,
        binding_revision=monitoring.binding_revision if monitoring is not None else None)
    paths=(inputs.access_file,inputs.ai_config,inputs.monitoring_config,
        inputs.policy_directory/'management_assistant_policy.json',inputs.policy_directory/'tool_policies.json')
    bindings['config_files']={str(p):[p.stat().st_dev,p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns]
        if p.exists() else None for p in paths}
    return access,ai,source_config,grant,_hash(bindings)

