"""Non-secret QQ configuration, independent from Web AI preferences and credentials."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import uuid

from apps.ai_backend.tools.policy import ToolPolicyError
from .management_policy import _check_path, _unique_object, _writer_lock


class QQSettingsError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def default_settings():
    return dict(enabled=False, ai_enabled=False, app_id='', group_id='', members=[],
                max_output_tokens=2048, event_notifications_enabled=False)


def validate_settings(value):
    if not isinstance(value, dict) or set(value) != set(default_settings()):
        raise QQSettingsError('QQ_SETTINGS_INVALID')
    for key in ('enabled', 'ai_enabled', 'event_notifications_enabled'):
        if type(value[key]) is not bool:
            raise QQSettingsError('QQ_SETTINGS_INVALID')
    if type(value['max_output_tokens']) is not int or not 1 <= value['max_output_tokens'] <= 4096:
        raise QQSettingsError('QQ_TOKEN_LIMIT_INVALID')
    if not isinstance(value['app_id'], str) or (value['app_id'] and not re.fullmatch(r'[0-9]{5,32}', value['app_id'])):
        raise QQSettingsError('QQ_IDENTITY_INVALID')
    if not isinstance(value['group_id'], str) or (value['group_id'] and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value['group_id'])):
        raise QQSettingsError('QQ_IDENTITY_INVALID')
    members = value['members']
    if (not isinstance(members, list) or len(members) > 4
            or any(not isinstance(m, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', m) for m in members)
            or len(set(members)) != len(members)):
        raise QQSettingsError('QQ_IDENTITY_INVALID')
    complete = bool(value['app_id'] and value['group_id'] and members)
    if (value['enabled'] or value['ai_enabled'] or value['event_notifications_enabled']
            or value['app_id'] or value['group_id'] or members) and not complete:
        raise QQSettingsError('QQ_IDENTITY_INCOMPLETE')
    if (value['ai_enabled'] or value['event_notifications_enabled']) and not value['enabled']:
        raise QQSettingsError('QQ_ENABLE_REQUIRED')
    return {**value, 'members': list(members)}


class QQSettingsStore:
    """Atomic, CAS-protected non-secret settings; no credential or database reads."""
    def __init__(self, path):
        self.path = Path(path).absolute()
        self.lock = threading.RLock()

    def read(self):
        try:
            _check_path(self.path)
            try:
                with self.path.open('rb') as stream:
                    raw = stream.read(8193)
            except FileNotFoundError:
                return dict(revision=0, settings=default_settings(), secret_saved_for_app=None)
            value = json.loads(raw, object_pairs_hook=_unique_object)
            if (len(raw) > 8192 or not isinstance(value, dict)
                    or set(value) != {'schema_version', 'revision', 'settings', 'secret_saved_for_app'}
                    or value['schema_version'] != 1 or type(value['schema_version']) is not int
                    or type(value['revision']) is not int or not 0 <= value['revision'] < 2**53
                    or value['secret_saved_for_app'] is not None and not re.fullmatch(r'[0-9]{5,32}', value['secret_saved_for_app'])):
                raise ValueError()
            validate_settings(value['settings'])
            return {k: v for k, v in value.items() if k != 'schema_version'}
        except (OSError, ValueError, TypeError, RecursionError, ToolPolicyError):
            raise QQSettingsError('QQ_SETTINGS_STORAGE_ERROR') from None

    def token_snapshot(self):
        value = self.read()
        return dict(revision=value['revision'], max_output_tokens=value['settings']['max_output_tokens'])

    @contextmanager
    def writing(self):
        try:
            with self.lock:
                _check_path(self.path)
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with _writer_lock(self.path.with_suffix('.lock')):
                    yield
        except QQSettingsError:
            raise
        except ToolPolicyError as error:
            raise QQSettingsError('QQ_SETTINGS_BUSY' if error.code == 'TOOL_POLICY_BUSY' else 'QQ_SETTINGS_STORAGE_ERROR') from None
        except (OSError, ValueError):
            raise QQSettingsError('QQ_SETTINGS_STORAGE_ERROR') from None

    def write_locked(self, value):
        if not 0 <= value['revision'] < 2**53:
            raise QQSettingsError('QQ_SETTINGS_STORAGE_ERROR')
        temporary = self.path.with_name('.qq-settings-' + uuid.uuid4().hex + '.tmp')
        try:
            _check_path(self.path)
            with temporary.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(dict(schema_version=1, **value), stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


class QQSettingsService:
    def __init__(self, project_root, data_root, config_directory, *, configuration_bridge, secret_writer_factory=None,
                 pairing_factory=None):
        self.project_root = Path(project_root).absolute()
        self.data_root = Path(data_root).absolute()
        self.config_directory = Path(config_directory).absolute()
        self.store = QQSettingsStore(self.data_root / 'qq-bot-settings.json')
        self._configuration_bridge = configuration_bridge
        self.secret_writer_factory = secret_writer_factory
        self.pairing_factory, self._pairing = pairing_factory, None
        self._pairing_lock = threading.RLock()
        self.browser_token = secrets.token_urlsafe(32)

    @property
    def bridge(self):
        if callable(self._configuration_bridge):
            self._configuration_bridge = self._configuration_bridge()
        return self._configuration_bridge

    def _state(self):
        stored = self.store.read()
        try:
            bridge = self.bridge.read_nonsecret()
            if type(bridge['configured']) is not bool or not isinstance(bridge['revision'], str):
                raise ValueError()
            revision = hashlib.sha256(json.dumps([stored, bridge['revision']], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            settings = validate_settings(bridge['settings'] if bridge['configured'] else stored['settings'])
        except Exception:
            raise QQSettingsError('QQ_CONFIGURATION_UNAVAILABLE') from None
        return stored, bridge, revision, settings

    def public(self):
        stored, bridge, revision, settings = self._state()
        return dict(revision=revision, settings=settings, configured=bridge['configured'],
                    agent_mode=bridge.get('agent_mode', 'current'), tools=bridge.get('tools', []),
                    provider=bridge.get('provider'), model=bridge.get('model'), preset=bridge.get('preset'),
                    binding=dict(data_root=str(self.data_root), instance_id=bridge.get('instance_id'), device_id=bridge.get('device_id')),
                    recipient_available=bool(bridge.get('recipient_available')), recipient_ref=bridge.get('recipient_ref'),
                    runtime_status=bridge.get('runtime_status', 'NOT_CHECKED'), restart_required=True,
                    secret_status='SAVED_FOR_THIS_APP' if settings['app_id'] and stored['secret_saved_for_app'] == settings['app_id'] else 'NOT_CHECKED',
                    max_allowed_output_tokens=4096, token_unit='PER_MODEL_HTTP_REQUEST', network_requests=0, database_opened=False)

    def _pairing_manager(self):
        if self._pairing is None:
            def supplier():
                # Called only after start's explicit network confirmation and process ownership.
                return self._writer().credentials.resolve('FISHERY_QQ_APP_SECRET')
            if self.pairing_factory is not None:
                self._pairing = self.pairing_factory()
            else:
                from apps.qq_bot.private_pairing import PairingManager
                self._pairing = PairingManager(self.project_root, self.config_directory, secret_supplier=supplier)
        return self._pairing

    def pairing_status(self):
        with self._pairing_lock:
            return self._pairing.status() if self._pairing is not None else dict(phase='IDLE', code='PRIVATE_PAIRING_IDLE')

    def pairing_start(self, value):
        with self._pairing_lock:
            stored, bridge, revision, settings = self._check_revision(value, {'revision', 'confirm_network'})
            if value['confirm_network'] is not True:
                raise QQSettingsError('PRIVATE_PAIRING_NETWORK_APPROVAL_REQUIRED')
            if not bridge['configured']:
                raise QQSettingsError('PRIVATE_PAIRING_SAVE_IDENTITY_FIRST')
            def validate():
                if self._state()[2] != revision:
                    raise QQSettingsError('QQ_SETTINGS_STALE')
            def bind(path):
                with self.store.writing():
                    validate()
                    self.bridge.bind_verified_recipient(path, expected_revision=bridge['revision'])
            try:
                return self._pairing_manager().start(settings['app_id'], settings['group_id'], validate=validate, bind=bind)
            except Exception as error:
                raise QQSettingsError(self._pairing_error(error)) from None

    @staticmethod
    def _pairing_error(error):
        code = getattr(error, 'code', '')
        return code if isinstance(code, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,80}', code) else 'PRIVATE_PAIRING_FAILED'

    def pairing_action(self, value, *, confirm=False):
        keys = {'pairing_id', 'user_ref', 'confirm_active_test'} if confirm else {'pairing_id'}
        if type(value) is not dict or set(value) != keys:
            raise QQSettingsError('QQ_SETTINGS_INVALID')
        if confirm and value['confirm_active_test'] is not True:
            raise QQSettingsError('PRIVATE_PAIRING_ACTIVE_APPROVAL_REQUIRED')
        with self._pairing_lock:
            manager = self._pairing
        if manager is None:
            raise QQSettingsError('PRIVATE_PAIRING_NOT_FOUND')
        try:
            return manager.confirm(value['pairing_id'], value['user_ref']) if confirm else manager.cancel(value['pairing_id'])
        except Exception as error:
            raise QQSettingsError(self._pairing_error(error)) from None

    def close(self):
        with self._pairing_lock:
            manager = self._pairing
        if manager is not None:
            manager.close()

    def _check_revision(self, value, keys):
        if not isinstance(value, dict) or set(value) != keys or not isinstance(value.get('revision'), str):
            raise QQSettingsError('QQ_SETTINGS_INVALID')
        current = self._state()
        if not secrets.compare_digest(value['revision'], current[2]):
            raise QQSettingsError('QQ_SETTINGS_STALE')
        return current

    def save(self, value):
        with self.store.writing():
            stored, bridge, _, _ = self._check_revision(value, {'revision', 'settings'})
            if stored['revision'] >= 2**53 - 1:
                raise QQSettingsError('QQ_SETTINGS_STORAGE_ERROR')
            settings = validate_settings(value['settings'])
            if settings['event_notifications_enabled'] and not bridge.get('recipient_available'):
                raise QQSettingsError('QQ_VERIFIED_RECIPIENT_REQUIRED')
            try:
                self.bridge.apply(settings, expected_revision=bridge['revision'])
            except Exception as error:
                code = getattr(error, 'code', '')
                code = {'QQ_SETTINGS_CONFLICT':'QQ_SETTINGS_STALE',
                        'EVENT_RECIPIENT_BINDING_REQUIRED':'QQ_VERIFIED_RECIPIENT_REQUIRED'}.get(code, code)
                allowed = {'QQ_SETTINGS_STALE', 'QQ_CONFIGURATION_STALE', 'QQ_VERIFIED_RECIPIENT_REQUIRED', 'MANAGEMENT_CONFIGURATION_CONFLICT'}
                raise QQSettingsError(code if code in allowed else 'QQ_CONFIGURATION_SAVE_FAILED') from None
            self.store.write_locked(dict(revision=stored['revision'] + 1, settings=settings,
                                         secret_saved_for_app=stored['secret_saved_for_app']))
        return self.public()

    def _writer(self):
        if self.secret_writer_factory is not None:
            return self.secret_writer_factory()
        from apps.ai_backend.credentials import CredentialStore
        from apps.ai_backend.project_env import ProjectEnvWriter
        from .runtime.locations import private_project_location
        location = private_project_location(self.project_root)
        credentials = CredentialStore(location.env_path, private_location=location)
        return ProjectEnvWriter(location.env_path.parent, credentials, require_git_ignored=False)

    def save_secret(self, value):
        with self.store.writing():
            stored, _, _, settings = self._check_revision(value, {'revision', 'app_secret', 'replace_existing'})
            if stored['revision'] >= 2**53 - 1:
                raise QQSettingsError('QQ_SETTINGS_STORAGE_ERROR')
            secret = value['app_secret']
            if (not settings['app_id'] or type(value['replace_existing']) is not bool
                    or not isinstance(secret, str) or not 1 <= len(secret) <= 4096
                    or not secret.isascii() or any(ord(c) <= 32 or ord(c) >= 127 for c in secret)):
                raise QQSettingsError('QQ_SECRET_INVALID')
            from apps.ai_backend.providers import AuthSpec
            from apps.ai_backend.project_env import EnvWriteError
            try:
                writer = self._writer()
                state = writer.inspect('FISHERY_QQ_APP_SECRET', AuthSpec.REQUIRED_BEARER)
                if state['exists'] and not value['replace_existing']:
                    raise QQSettingsError('QQ_SECRET_REPLACE_CONFIRMATION_REQUIRED')
                writer.mutate('FISHERY_QQ_APP_SECRET', AuthSpec.REQUIRED_BEARER,
                              action='replace' if state['exists'] else 'create', expected_revision=state['revision'], secret=secret)
            except EnvWriteError:
                raise QQSettingsError('QQ_SECRET_SAVE_FAILED') from None
            except QQSettingsError:
                raise
            except Exception:
                raise QQSettingsError('QQ_SECRET_SAVE_FAILED') from None
            self.store.write_locked(dict(revision=stored['revision'] + 1, settings=stored['settings'],
                                         secret_saved_for_app=settings['app_id']))
        return self.public()
