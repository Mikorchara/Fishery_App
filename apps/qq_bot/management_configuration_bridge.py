"""Non-secret Web configuration bridge; no credentials, SQLite or network I/O.

Only trusted constructor paths select the instance. Saves publish a complete
configuration generation, retaining the old directory for local recovery.
"""
from pathlib import Path
import json
import os
import uuid

from apps.ai_backend.secure_files import exclusive_lock
from apps.ai_service.channel_trial import PRESET
from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.runtime.release_contracts import _hash
from .contracts import BotError
from .management_config import ROOT, MARKER
from .trial_configuration import local_path, read_json, write_new


class QQConfigurationBridge:
    def __init__(self, project_root, data_root, config_directory):
        self.project_root=local_path(project_root).resolve()
        self.data_root=local_path(data_root).resolve()
        self.directory=local_path(config_directory).resolve()
        if self.project_root!=ROOT.resolve():raise BotError('MANAGEMENT_PROJECT_PATH_MISMATCH')
        if (not self.data_root.is_relative_to(self.project_root/'outputs')
                or not self.directory.is_relative_to(self.project_root/'outputs')
                or self.directory==self.data_root or self.directory.is_relative_to(self.data_root)
                or self.data_root.is_relative_to(self.directory)):
            raise BotError('INITIALIZATION_PATH_CONFLICT')

    def _revision(self):
        values=[]
        for name in ('request.json','access.json','ai.json','monitoring.json','scope.json',
                     'policy/management_assistant_policy.json','policy/tool_policies.json'):
            path=self.directory/name
            values.append((name,read_json(path) if path.is_file() else None))
        return _hash(values)

    def read_nonsecret(self):
        revision=self._revision();profile=assistant_profile(PRESET)
        result=dict(configured=False,revision=revision,recipient_available=False,recipient_ref=None,
            runtime_status='NOT_CONFIGURED',provider=profile.service_id,model=profile.model,preset=PRESET,
            instance_id='management-isolated',device_id='sim-pond-1',
            binding=dict(data_root=str(self.data_root),instance_id='management-isolated',device_id='sim-pond-1'))
        if not (self.directory/'request.json').is_file():return result
        from .configuration import load_access
        from .ai_configuration import load_ai_config
        request=read_json(self.directory/'request.json')
        access=load_access(self.directory/'access.json');ai=load_ai_config(self.directory/'ai.json')
        source=read_json(self.directory/'monitoring.json')
        if Path(source['data_root']).resolve()!=self.data_root:raise BotError('MANAGEMENT_INSTANCE_BINDING_MISMATCH')
        group=next((g for g in access.groups if g.group_id==request['inputs']['group_id']),None)
        if group is None:raise BotError('INVALID_MANAGEMENT_REQUEST')
        recipient=None
        recipient_file=request.get('event_recipient_file') or request.get('verified_recipient_file')
        if recipient_file:
            from .event_recipients import load_recipient
            recipient=load_recipient(local_path(recipient_file),access.app_id)
        result.update(configured=True,runtime_status='CONFIGURED_RESTART_REQUIRED',
            settings=dict(enabled=request['enabled'],ai_enabled=request.get('ai_enabled',request['enabled']),
                app_id=access.app_id,group_id=group.group_id,members=list(request['members']),
                max_output_tokens=ai.budget.max_output_tokens,event_notifications_enabled=bool(request.get('event_recipient_file'))),
            recipient_available=recipient is not None,recipient_ref=recipient['user_ref'] if recipient else None)
        return result

    def apply(self, settings, *, expected_revision):
        from .management_cli import _configuration_inputs, _write_configuration
        if not self.directory.parent.is_dir():raise BotError('INITIALIZATION_PARENT_MISSING')
        with exclusive_lock(self.directory.parent/'.qq-configuration.lock'):
            current=self.read_nonsecret()
            if current['revision']!=expected_revision:raise BotError('QQ_SETTINGS_CONFLICT')
            # An entirely empty disabled draft is owned by QQSettingsStore only.
            if not settings['app_id'] and not settings['group_id'] and not settings['members']:
                if current['configured']:raise BotError('QQ_CONFIGURATION_IDENTITY_REQUIRED')
                return current
            root,cfg,access,ai=_configuration_inputs(self.data_root,self.directory,
                app_id=settings['app_id'],group_id=settings['group_id'],members=tuple(settings['members']),
                continuous=True,output_tokens=settings['max_output_tokens'],ai_enabled=settings['ai_enabled'])
            marker=read_json(root/'qq-isolated-instance.json')
            if marker!=dict(contract=MARKER,root=str(root),instance_id='management-isolated',
                            device_id='sim-pond-1',source='SIMULATOR'):
                raise BotError('ISOLATED_INSTANCE_PROOF_REQUIRED')
            for name in ('monitoring.sqlite3','knowledge.sqlite3'):
                path=local_path(root/name)
                if not path.is_file() or path.stat().st_size==0:raise BotError('MANAGEMENT_INSTANCE_MISSING')
            recipient_path=None;old=current.get('settings',{})
            if current['configured'] and old.get('app_id')==settings['app_id'] and current['recipient_available']:
                previous=read_json(self.directory/'request.json')
                recipient_path=local_path(previous.get('event_recipient_file') or previous['verified_recipient_file'])
            if settings['event_notifications_enabled']:
                if recipient_path is None:
                    raise BotError('EVENT_RECIPIENT_BINDING_REQUIRED')
            stage=cfg.parent/('.qq-config-stage-'+uuid.uuid4().hex);stage.mkdir()
            _write_configuration(root,stage,access=access,ai=ai,members=tuple(settings['members']),
                enable=settings['enabled'],continuous=True)
            request=read_json(stage/'request.json')
            for field,name in (('access_file','access.json'),('ai_config','ai.json'),
                               ('monitoring_config','monitoring.json'),('policy_directory','policy')):
                request['inputs'][field]=str(cfg/name)
            if recipient_path is not None:
                if recipient_path.is_relative_to(cfg):
                    from apps.ai_backend.secure_files import write_private
                    destination=stage/recipient_path.relative_to(cfg)
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    value=read_json(recipient_path)
                    write_private(destination,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
                request['event_recipient_file' if settings['event_notifications_enabled'] else 'verified_recipient_file']=str(recipient_path)
            # Only a newly created staging file is replaced here; historical
            # approvals/results/credentials are neither read nor rewritten.
            replacement=stage/'request.next.json';write_new(replacement,request)
            os.replace(replacement,stage/'request.json')
            if self._revision()!=expected_revision:raise BotError('QQ_SETTINGS_CONFLICT')
            backup=None
            if cfg.exists():
                backup=cfg.parent/('.qq-config-previous-'+uuid.uuid4().hex)
                cfg.rename(backup)
            try:stage.rename(cfg)
            except Exception:
                if backup is not None and not cfg.exists():backup.rename(cfg)
                raise BotError('QQ_CONFIGURATION_PUBLISH_FAILED') from None
            return self.read_nonsecret()
