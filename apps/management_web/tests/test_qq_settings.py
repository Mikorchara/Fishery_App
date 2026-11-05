"""QQ settings use synthetic config/credentials and never require an Assistant or DB."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from apps.ai_service.qq_settings import QQSettingsError, QQSettingsService, QQSettingsStore, default_settings
from apps.management_web.app import create_app


class FakeBridge:
    def __init__(self):
        self.version = 0
        self.configured = False
        self.settings = default_settings()
        self.recipient = False
        self.writes = []

    def read_nonsecret(self):
        return dict(configured=self.configured, revision=str(self.version), settings=deepcopy(self.settings),
                    instance_id='synthetic-instance', device_id='synthetic-device',
                    recipient_available=self.recipient, recipient_ref='synthetic-ref' if self.recipient else None,
                    runtime_status='NOT_CHECKED')

    def apply(self, settings, *, expected_revision):
        if expected_revision != str(self.version):
            raise QQSettingsError('QQ_CONFIGURATION_STALE')
        self.writes.append(deepcopy(settings))
        self.settings = deepcopy(settings)
        self.configured = bool(settings['app_id'])
        self.version += 1


class QQSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bridge = FakeBridge()
        self.writer = Mock()
        self.writer.inspect.return_value = dict(exists=False, revision='synthetic-secret-revision')
        self.factory = Mock(return_value=self.writer)
        self.service = QQSettingsService(self.root, self.root/'data', self.root/'config',
            configuration_bridge=self.bridge, secret_writer_factory=self.factory)
        self.client = create_app(qq_settings_service=self.service).test_client()

    def get(self):
        return self.client.get('/api/settings/qq').get_json()

    def post(self, settings=None, **kwargs):
        data = dict(revision=self.get()['revision'], settings=settings or default_settings())
        data.update(kwargs)
        return self.client.post('/api/settings/qq', json=data, headers={'X-Management-QQ':self.service.browser_token})

    def identity(self):
        return dict(default_settings(), app_id='123456', group_id='synthetic-group', members=['synthetic-member'], enabled=True)

    def test_get_without_assistant_reads_no_credentials_database_or_network(self):
        with patch('sqlite3.connect', side_effect=AssertionError('DB forbidden')), \
                patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            value = self.get()
        self.assertEqual(value['settings']['max_output_tokens'], 2048)
        self.assertEqual(value['secret_status'], 'NOT_CHECKED')
        self.assertFalse(value['configured'])
        self.assertFalse((self.root/'data').exists())
        self.factory.assert_not_called()
        self.assertEqual(self.client.get('/api/settings').status_code, 503)

    def test_token_draft_is_persistent_and_does_not_require_identity(self):
        settings = dict(default_settings(), max_output_tokens=4096)
        response = self.post(settings)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['configured'])
        store = QQSettingsStore(self.root/'data'/'qq-bot-settings.json')
        self.assertEqual(store.token_snapshot(), dict(revision=1, max_output_tokens=4096))
        self.assertFalse((self.root/'data'/'settings.json').exists())
        self.factory.assert_not_called()

    def test_saved_identity_and_ai_are_explicit_and_bounded(self):
        settings = dict(self.identity(), ai_enabled=True)
        response = self.post(settings)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['settings'], settings)
        self.assertTrue(response.get_json()['restart_required'])
        self.assertEqual(response.get_json()['binding']['device_id'], 'synthetic-device')
        self.assertEqual(len(self.bridge.writes), 1)

    def test_invalid_token_identity_unknown_fields_paths_and_secret_are_rejected(self):
        for token in (0, 4097, 1.5, True, '2048'):
            response = self.post(dict(default_settings(), max_output_tokens=token))
            self.assertEqual(response.get_json()['error_code'], 'QQ_TOKEN_LIMIT_INVALID')
        for change in (dict(data_root='C:/other'), dict(app_secret='synthetic-secret'), dict(members=['x']*5),
                       dict(enabled=True), dict(app_id='../wrong'), dict(members=['repeat','repeat'])):
            self.assertEqual(self.post(dict(default_settings(), **change)).status_code, 409)
        self.assertEqual(self.bridge.writes, [])

    def test_cas_includes_external_configuration_change(self):
        revision = self.get()['revision']
        self.bridge.version += 1
        response = self.post(revision=revision)
        self.assertEqual(response.get_json()['error_code'], 'QQ_SETTINGS_STALE')
        self.assertEqual(self.bridge.writes, [])

    def test_event_notification_requires_existing_verified_recipient(self):
        settings = dict(self.identity(), event_notifications_enabled=True)
        self.assertEqual(self.post(settings).get_json()['error_code'], 'QQ_VERIFIED_RECIPIENT_REQUIRED')
        self.bridge.recipient = True
        response = self.post(settings)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['recipient_ref'], 'synthetic-ref')

    def test_secret_is_explicit_private_write_never_returned_or_saved_in_settings(self):
        self.assertEqual(self.post(self.identity()).status_code, 200)
        self.factory.assert_not_called()
        response = self.client.post('/api/settings/qq/secret', json=dict(revision=self.get()['revision'],
            app_secret='fictional-secret-only', replace_existing=False), headers={'X-Management-QQ':self.service.browser_token})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['secret_status'], 'SAVED_FOR_THIS_APP')
        self.assertNotIn('fictional-secret-only', response.get_data(as_text=True))
        self.assertNotIn('fictional-secret-only', (self.root/'data'/'qq-bot-settings.json').read_text())
        self.writer.mutate.assert_called_once()
        self.assertEqual(self.writer.mutate.call_args.kwargs['action'], 'create')
        self.get()
        self.assertEqual(self.factory.call_count, 1)

    def test_existing_secret_requires_explicit_replace_and_error_is_bounded(self):
        self.post(self.identity())
        self.writer.inspect.return_value = dict(exists=True, revision='r')
        response = self.client.post('/api/settings/qq/secret', json=dict(revision=self.get()['revision'],
            app_secret='fictional-secret-only', replace_existing=False), headers={'X-Management-QQ':self.service.browser_token})
        self.assertEqual(response.get_json()['error_code'], 'QQ_SECRET_REPLACE_CONFIRMATION_REQUIRED')
        self.writer.mutate.assert_not_called()

    def test_local_token_json_origin_and_body_boundary(self):
        value = dict(revision=self.get()['revision'], settings=default_settings())
        self.assertEqual(self.client.post('/api/settings/qq', json=value).status_code, 403)
        for remote in ('192.0.2.4', 'bad-address'):
            self.assertEqual(self.client.get('/api/settings/qq', environ_base={'REMOTE_ADDR':remote}).status_code, 403)
        self.assertEqual(self.client.get('/api/settings/qq', headers={'Origin':'https://evil.invalid'}).status_code, 403)
        self.assertEqual(self.client.get('/api/settings/qq', headers={'Host':'evil.invalid'}).status_code, 403)
        self.assertEqual(self.client.post('/api/settings/qq', data='{}', headers={'X-Management-QQ':self.service.browser_token}).status_code, 400)
        self.assertEqual(self.client.post('/api/settings/qq', data='x'*8193,
            headers={'X-Management-QQ':self.service.browser_token,'Content-Type':'application/json'}).status_code, 413)
        for malformed in ('{"revision":"a","revision":"b"}', '{"settings":{"enabled":true,"enabled":false}}', '{"value":NaN}'):
            response = self.client.post('/api/settings/qq', data=malformed,
                headers={'X-Management-QQ':self.service.browser_token,'Content-Type':'application/json'})
            self.assertEqual(response.get_json()['error_code'], 'QQ_SETTINGS_JSON_INVALID')

    def test_atomic_store_failure_preserves_existing_file(self):
        self.post()
        path = self.root/'data'/'qq-bot-settings.json'
        before = path.read_bytes()
        with patch('apps.ai_service.qq_settings.os.replace', side_effect=OSError('sensitive details')):
            response = self.post(dict(default_settings(), max_output_tokens=1024))
        self.assertEqual(response.get_json()['error_code'], 'QQ_SETTINGS_STORAGE_ERROR')
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn('sensitive', response.get_data(as_text=True))

    def test_duplicate_json_and_symlink_storage_fail_closed(self):
        path = self.root/'data'/'qq-bot-settings.json'
        path.parent.mkdir()
        path.write_text('{"schema_version":1,"schema_version":1}')
        self.assertEqual(self.client.get('/api/settings/qq').get_json()['error_code'], 'QQ_SETTINGS_STORAGE_ERROR')


class QQSettingsBridgeTests(unittest.TestCase):
    def test_real_bridge_generates_independent_configuration_without_database_or_secret_reads(self):
        from apps.qq_bot.management_configuration_bridge import QQConfigurationBridge
        from apps.qq_bot.management_config import ROOT, MARKER, check_request
        from apps.management_paths import ManagementPaths
        from apps.management_web.instance import initialize_instance
        temporary_root = ROOT/'outputs'/'test-tmp'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as name:
            test_root = Path(name)
            data_root = test_root/'synthetic-data'
            config_root = test_root/'synthetic-config'
            initialize_instance(ManagementPaths.resolve(ROOT, data_root=data_root))
            (data_root/'qq-isolated-instance.json').write_text(json.dumps(dict(contract=MARKER, root=str(data_root),
                instance_id='management-isolated', device_id='sim-pond-1', source='SIMULATOR')))
            databases = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in data_root.glob('*.sqlite3')}
            service = QQSettingsService(ROOT, data_root, config_root,
                configuration_bridge=QQConfigurationBridge(ROOT, data_root, config_root))
            with patch('sqlite3.connect', side_effect=AssertionError('DB forbidden')), \
                    patch('apps.ai_backend.credentials.CredentialStore.resolve', side_effect=AssertionError('secret forbidden')), \
                    patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
                initial = service.public()
                self.assertEqual(initial['model'], 'qwen3.8-flash')
                self.assertFalse(config_root.exists())
                saved = service.save(dict(revision=initial['revision'], settings=dict(default_settings(),
                    app_id='123456', group_id='synthetic-group', members=['synthetic-member'], enabled=True, ai_enabled=True)))
                self.assertTrue(saved['configured'])
                self.assertEqual(saved['settings']['max_output_tokens'], 2048)
                self.assertEqual(json.loads((config_root/'request.json').read_text())['schema_version'], 2)
                saved = service.save(dict(revision=saved['revision'], settings=dict(saved['settings'], max_output_tokens=1024)))
                request, summary = check_request(config_root/'request.json')
                self.assertTrue(request.continuous)
                self.assertEqual(request.output_tokens, 1024)
                self.assertFalse(summary['database_opened'])
            self.assertEqual(databases, {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in databases})
            self.assertEqual(service.store.token_snapshot()['max_output_tokens'], 1024)
            self.assertEqual(len(list(test_root.glob('.qq-config-previous-*'))), 1)


if __name__ == '__main__':
    unittest.main()
