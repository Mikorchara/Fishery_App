"""Local recipient list validation and Web pairing publication with fake identities."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from apps.ai_backend.secure_files import write_private
from apps.qq_bot.contracts import BotError
from apps.qq_bot.event_recipients import (
    CONTRACT, MAX_RECIPIENTS, RECIPIENTS_CONTRACT, load_recipients, recipient_ref,
)
from apps.qq_bot.management_cli import initialize_demo
from apps.qq_bot.management_config import ROOT, check_request
from apps.qq_bot.management_configuration_bridge import QQConfigurationBridge
from apps.qq_bot.trial_configuration import read_json


APP_ID = '123456789'


def proof(user, *, app_id=APP_ID, digest='a' * 64):
    return dict(contract=CONTRACT, app_id=app_id, user_openid=user,
                user_ref=recipient_ref(app_id, user), active_probe_sha256=digest)


def publish(path, value):
    write_private(path, (json.dumps(value) + '\n').encode('utf8'))


class RecipientListTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(dir=ROOT/'outputs/test-tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_strict_list_accepts_original_proof_and_sorts_valid_entries(self):
        a, b = proof('private-a'), proof('private-b')
        single = self.root/'single.json'
        publish(single, a)
        self.assertEqual(load_recipients(single, APP_ID), (a,))
        multiple = self.root/'multiple.json'
        expected = tuple(sorted([a, b], key=lambda entry: entry['user_ref']))
        publish(multiple, dict(contract=RECIPIENTS_CONTRACT, recipients=list(reversed(expected))))
        self.assertEqual(load_recipients(multiple, APP_ID), expected)
        invalid = (
            [], [a, a], [a, proof('different-app', app_id='987654321')],
            [dict(a, active_probe_sha256='invalid')], [a, 'other'],
            [proof(f'over-{i}') for i in range(MAX_RECIPIENTS + 1)],
        )
        for index, entries in enumerate(invalid):
            path = self.root/f'invalid-{index}.json'
            publish(path, dict(contract=RECIPIENTS_CONTRACT, recipients=entries))
            with self.subTest(index=index), self.assertRaisesRegex(BotError, 'EVENT_RECIPIENT_BINDING_INVALID'):
                load_recipients(path, APP_ID)


class RecipientBridgeTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(dir=ROOT/'outputs/test-tmp')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        data, config = root/'instance', root/'config'
        self.request = initialize_demo(data, config, app_id=APP_ID,
            group_id='fake-pairing-group', members=('synthetic-group-member',), enable=True)
        self.bridge = QQConfigurationBridge(ROOT, data, config)
        initial = self.bridge.read_nonsecret()
        self.bridge.apply(initial['settings'], expected_revision=initial['revision'])

    def bind(self, user, label, **kwargs):
        path = self.request.parent/f'event-recipient-{label}.json'
        publish(path, proof(user, **kwargs))
        return self.bridge.bind_verified_recipient(path, expected_revision=self.bridge.read_nonsecret()['revision'])

    def enable(self):
        current = self.bridge.read_nonsecret()
        return self.bridge.apply(dict(current['settings'], event_notifications_enabled=True),
                                 expected_revision=current['revision'])

    def test_append_keeps_existing_binding_disables_sending_and_survives_resave(self):
        first = recipient_ref(APP_ID, 'private-a')
        second = recipient_ref(APP_ID, 'private-b')
        self.assertEqual(self.bind('private-a', 'a')['recipient_refs'], [first])
        self.assertTrue(self.enable()['settings']['event_notifications_enabled'])
        self.assertTrue(self.bind('private-a', 'a-repeat', digest='b' * 64)['settings']['event_notifications_enabled'])
        current = self.bind('private-b', 'b')
        self.assertEqual(current['recipient_refs'], sorted([first, second]))
        self.assertFalse(current['settings']['event_notifications_enabled'])
        self.assertNotIn('private-a', json.dumps(current))
        enabled = self.enable()
        self.assertEqual(enabled['recipient_refs'], current['recipient_refs'])
        self.assertTrue(enabled['settings']['event_notifications_enabled'])
        stored = read_json(self.request)
        self.assertEqual([entry['user_ref'] for entry in load_recipients(stored['event_recipient_file'], APP_ID)],
                         current['recipient_refs'])

    def test_limit_stale_removal_and_explicit_revocation(self):
        state = self.bridge.read_nonsecret()
        old_revision = state['revision']
        for index in range(MAX_RECIPIENTS):
            state = self.bind(f'private-{index}', str(index))
        with self.assertRaisesRegex(BotError, 'EVENT_RECIPIENT_LIMIT'):
            self.bind('private-over', 'over')
        self.assertEqual(self.bridge.read_nonsecret()['recipient_refs'], state['recipient_refs'])
        with self.assertRaisesRegex(BotError, 'QQ_SETTINGS_CONFLICT'):
            self.bridge.remove_verified_recipient(state['recipient_ref'], expected_revision=old_revision)
        state = self.enable()
        removed = state['recipient_ref']
        original = self.request.read_bytes()
        with patch('apps.ai_backend.secure_files.atomic_replace', side_effect=OSError('publication')):
            with self.assertRaises(OSError):
                self.bridge.remove_verified_recipient(removed, expected_revision=state['revision'])
        self.assertEqual(self.request.read_bytes(), original)
        previous = self.request.parent.glob('request.before-recipient-change-*.json')
        self.assertTrue(any(backup.read_bytes() == original for backup in previous))
        while state['recipient_refs']:
            ref = state['recipient_ref']
            state = self.bridge.remove_verified_recipient(ref, expected_revision=state['revision'])
            self.assertNotIn(ref, state['recipient_refs'])
            self.assertFalse(state['settings']['event_notifications_enabled'])
        self.assertFalse(state['recipient_available'])
        self.assertIsNone(state['recipient_ref'])
        self.assertNotIn('verified_recipient_file', read_json(self.request))
        with self.assertRaisesRegex(BotError, 'EVENT_RECIPIENT_NOT_FOUND'):
            self.bridge.remove_verified_recipient(removed, expected_revision=state['revision'])

    def test_resave_refreshes_old_startup_scope_and_preserves_single_recipient(self):
        ref = recipient_ref(APP_ID, 'private-a')
        self.bind('private-a', 'a')
        self.enable()
        old_request = read_json(self.request)
        old_request['scope_sha256'] = '0' * 64
        self.request.write_bytes(json.dumps(old_request).encode('utf8'))
        with self.assertRaisesRegex(BotError, 'MANAGEMENT_SCOPE_REVIEW_REQUIRED'):
            check_request(self.request, offline=True)
        snapshot = self.bridge.read_nonsecret()
        with patch('socket.getaddrinfo', side_effect=AssertionError('network')), \
             patch('sqlite3.connect', side_effect=AssertionError('database')):
            self.bridge.apply(snapshot['settings'], expected_revision=snapshot['revision'])
            _, plan = check_request(self.request, offline=True)
        self.assertEqual(plan['event_notifications']['recipient_refs'], [ref])
        self.assertTrue(plan['enabled'])
        self.assertEqual(plan['network_requests'], 0)
