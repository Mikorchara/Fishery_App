"""Non-secret Web configuration bridge; no credentials, SQLite or network I/O.

Only trusted constructor paths select the instance. Saves publish a complete
configuration generation, retaining the old directory for local recovery.
"""
from pathlib import Path
import json
import os
import re
import uuid

from apps.ai_backend.secure_files import exclusive_lock
from apps.ai_service.channel_trial import PRESET
from apps.ai_service.runtime.assistant import assistant_profile
from apps.ai_service.runtime.release_contracts import _hash
from .contracts import BotError
from .event_recipients import MAX_RECIPIENTS, RECIPIENTS_CONTRACT, load_recipient, load_recipients, read_private
from .management_config import ROOT, MARKER
from .trial_configuration import local_path, read_json, write_new


def _recipient_path(request):
    path = request.get('event_recipient_file') or request.get('verified_recipient_file')
    return local_path(path) if path else None


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
        result=dict(configured=False,revision=revision,recipient_available=False,recipient_ref=None,recipient_refs=[],
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
        recipient_path = _recipient_path(request)
        recipients = load_recipients(recipient_path, access.app_id) if recipient_path is not None else ()
        refs = [recipient['user_ref'] for recipient in recipients]
        result.update(configured=True,runtime_status='CONFIGURED_RESTART_REQUIRED',
            agent_mode=request.get('agent_mode','current'),
            tools=list(next(g.tools for g in ai.grants if g.group_id==group.group_id)),
            settings=dict(enabled=request['enabled'],ai_enabled=request.get('ai_enabled',request['enabled']),
                app_id=access.app_id,group_id=group.group_id,members=list(request['members']),
                max_output_tokens=ai.budget.max_output_tokens,event_notifications_enabled=bool(request.get('event_recipient_file'))),
            recipient_available=bool(refs),recipient_ref=refs[0] if refs else None,recipient_refs=refs)
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
                continuous=True,output_tokens=settings['max_output_tokens'],ai_enabled=settings['ai_enabled'],agent_mode='web')
            marker=read_json(root/'qq-isolated-instance.json')
            if marker!=dict(contract=MARKER,root=str(root),instance_id='management-isolated',
                            device_id='sim-pond-1',source='SIMULATOR'):
                raise BotError('ISOLATED_INSTANCE_PROOF_REQUIRED')
            for name in ('monitoring.sqlite3','knowledge.sqlite3'):
                path=local_path(root/name)
                if not path.is_file() or path.stat().st_size==0:raise BotError('MANAGEMENT_INSTANCE_MISSING')
            recipient_path=None;old=current.get('settings',{})
            if current['configured'] and old.get('app_id')==settings['app_id'] and current['recipient_available']:
                recipient_path=_recipient_path(read_json(self.directory/'request.json'))
            if settings['event_notifications_enabled']:
                if recipient_path is None:
                    raise BotError('EVENT_RECIPIENT_BINDING_REQUIRED')
            stage=cfg.parent/('.qq-config-stage-'+uuid.uuid4().hex);stage.mkdir()
            _write_configuration(root,stage,access=access,ai=ai,members=tuple(settings['members']),
                enable=settings['enabled'],continuous=True,agent_mode='web')
            request=read_json(stage/'request.json')
            for field,name in (('access_file','access.json'),('ai_config','ai.json'),
                               ('monitoring_config','monitoring.json'),('policy_directory','policy')):
                request['inputs'][field]=str(cfg/name)
            if recipient_path is not None:
                if recipient_path.is_relative_to(cfg):
                    from apps.ai_backend.secure_files import write_private
                    destination=stage/recipient_path.relative_to(cfg)
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    value=read_private(recipient_path)
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

    def bind_verified_recipient(self,path,*,expected_revision):
        """Called only with a new proof from the bounded Web pairing owner.

        Pairing holds the Bot OS lock. This lock/CAS serializes configuration
        publication without trying to acquire that same Bot lock recursively.
        """
        from .configuration import load_access
        target = local_path(path).resolve()
        if target.parent != self.directory or not target.name.startswith('event-recipient-'):
            raise BotError('PRIVATE_PAIRING_BINDING_INVALID')
        with exclusive_lock(self.directory.parent/'.qq-configuration.lock'):
            if self._revision() != expected_revision:
                raise BotError('QQ_SETTINGS_CONFLICT')
            request = read_json(self.directory/'request.json')
            if request.get('schema_version') not in (2, 3):
                raise BotError('PRIVATE_PAIRING_SAVE_IDENTITY_FIRST')
            app_id = load_access(self.directory/'access.json').app_id
            recipient = load_recipient(target, app_id)
            previous_path = _recipient_path(request)
            recipients = load_recipients(previous_path, app_id) if previous_path is not None else ()
            for current in recipients:
                if current['user_ref'] == recipient['user_ref']:
                    if current['user_openid'] != recipient['user_openid']:
                        raise BotError('EVENT_RECIPIENT_BINDING_INVALID')
                    return self.read_nonsecret()
            if len(recipients) >= MAX_RECIPIENTS:
                raise BotError('EVENT_RECIPIENT_LIMIT')
            self._publish_recipient_binding(request, (*recipients, recipient), expected_revision,
                                            single_target=target if not recipients else None)
            return self.read_nonsecret()

    def remove_verified_recipient(self, user_ref, *, expected_revision):
        """Revoke one binding without changing QQ group or AI permissions."""
        from .configuration import load_access
        if type(user_ref) is not str or not re.fullmatch('[0-9a-f]{12}', user_ref):
            raise BotError('EVENT_RECIPIENT_BINDING_INVALID')
        with exclusive_lock(self.directory.parent/'.qq-configuration.lock'):
            if self._revision() != expected_revision:
                raise BotError('QQ_SETTINGS_CONFLICT')
            request = read_json(self.directory/'request.json')
            path = _recipient_path(request)
            app_id = load_access(self.directory/'access.json').app_id
            recipients = load_recipients(path, app_id) if path is not None else ()
            retained = tuple(recipient for recipient in recipients if recipient['user_ref'] != user_ref)
            if retained == recipients:
                raise BotError('EVENT_RECIPIENT_NOT_FOUND')
            self._publish_recipient_binding(request, retained, expected_revision)
            return self.read_nonsecret()

    def _publish_recipient_binding(self, request, recipients, expected_revision, *, single_target=None):
        from apps.ai_backend.secure_files import atomic_replace, write_private

        # Keep every published recipient file immutable so the old request is
        # still valid if recording the new request fails or must be recovered.
        target = single_target
        if recipients and target is None:
            target = self.directory/('event-recipients-'+uuid.uuid4().hex+'.json')
            ordered = sorted(recipients, key=lambda entry: entry['user_ref'])
            value = ordered[0] if len(ordered) == 1 else dict(contract=RECIPIENTS_CONTRACT, recipients=ordered)
            write_private(target, (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())

        request_path = self.directory/'request.json'
        backup = self.directory/('request.before-recipient-change-'+uuid.uuid4().hex+'.json')
        write_private(backup, request_path.read_bytes())
        request.pop('event_recipient_file', None)
        request.pop('verified_recipient_file', None)
        if target is not None:
            request['verified_recipient_file'] = str(target)
        temporary = self.directory/('request.recipient-change-'+uuid.uuid4().hex+'.json')
        write_private(temporary, (json.dumps(request, ensure_ascii=False, indent=2)+'\n').encode())
        if self._revision() != expected_revision:
            raise BotError('QQ_SETTINGS_CONFLICT')
        atomic_replace(temporary, request_path)
