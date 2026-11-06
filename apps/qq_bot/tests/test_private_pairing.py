"""Fresh temporary pairing state, Fake Gateway and memory QQ HTTP only."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from queue import Queue, Empty
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import httpx
from apps.ai_backend.credentials import CredentialSnapshot, CredentialStatus
from apps.ai_service.runtime.release_contracts import _hash
from apps.qq_bot.contracts import BotError
from apps.qq_bot.event_recipients import load_recipient
from apps.qq_bot.management_config import process_lock, ensure_private_directory
from apps.qq_bot.private_pairing import PairingManager, match_private_message

APP, GROUP, USER = '123456789', 'synthetic-group', 'synthetic-private-user'


class Socket:
    def __init__(self):
        self.frames, self.closed, self.sent = Queue(), threading.Event(), []
        self.socket = self
        self.frames.put(dict(op=10, d=dict(heartbeat_interval=1000)))
        self.frames.put(dict(op=0, s=1, t='READY', d=dict(session_id='synthetic-session',
            user=dict(id='synthetic-bot'), application=dict(id=APP))))

    def send(self, value):
        data = json.loads(value)
        self.sent.append(data)
        if data['op'] == 1:self.frames.put(dict(op=11))

    def recv(self, timeout):
        if self.closed.is_set():raise OSError('synthetic close')
        try:return json.dumps(self.frames.get(timeout=timeout))
        except Empty:raise TimeoutError() from None

    def shutdown(self, *_):self.closed.set()
    def close(self):self.closed.set()
    def __enter__(self):return self
    def __exit__(self, *_):self.close()


def packet(challenge, *, user=USER, event='C2C_MESSAGE_CREATE', observed=None):
    return dict(op=0, s=2, t=event, d=dict(id='opaque:C2C@message~value', content=challenge,
        timestamp=(observed or datetime.now(timezone.utc)).isoformat(), author=dict(user_openid=user)))


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root/'config'
        self.config.mkdir()
        self.socket = Socket()
        self.posts, self.bindings, self.outcome = [], [], 'OK'
        self.secret = Mock(return_value=CredentialSnapshot('synthetic-app-secret', CredentialStatus('PRESENT','TEST',False)))
        def http(request):
            if request.url.path.endswith('/getAppAccessToken'):
                return httpx.Response(200, json=dict(access_token='synthetic-token', expires_in=3600))
            if request.url.path == '/gateway':
                return httpx.Response(200, json=dict(url='wss://api.bot.qq.com/websocket/'))
            self.posts.append(request)
            if self.outcome == 'UNKNOWN':raise httpx.ReadTimeout('not logged', request=request)
            if self.outcome == 'DENIED':return httpx.Response(400, json=dict(code=40034105, message='not logged'))
            return httpx.Response(200, json=dict(id='synthetic-accepted'))
        self.client = httpx.Client(transport=httpx.MockTransport(http))
        self.addCleanup(self.client.close)
        self.manager = self.make()
        self.addCleanup(self.manager.close)

    def make(self, **options):
        return PairingManager(self.root, self.config, secret_supplier=self.secret,
            client=self.client, connector=lambda _:self.socket, **options)

    def wait(self, predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:threading.Event().wait(.01)
        self.assertTrue(predicate(), self.manager.status())

    def start(self):
        result = self.manager.start(APP, GROUP, validate=lambda:None, bind=self.bindings.append)
        self.wait(lambda:self.manager._run.gateway.ready.is_set())
        return result

    def identify(self):
        result = self.start()
        self.socket.frames.put(packet(result['challenge_command']))
        self.wait(lambda:self.manager.status()['phase'] == 'AWAITING_CONFIRMATION')
        return result

    def test_authentication_nonce_and_explicit_confirmation_precede_single_active_post(self):
        result = self.identify()
        self.assertEqual(self.posts, [])
        snapshot = self.manager.status()
        self.assertNotIn('challenge_command', snapshot)
        self.assertNotIn(USER, json.dumps(snapshot))
        finished = self.manager.confirm(result['pairing_id'], snapshot['user_ref'])
        self.assertEqual(finished['phase'], 'BOUND')
        self.assertTrue(finished['api_accepted'])
        self.assertFalse(finished['client_display_confirmed'])
        self.assertTrue(finished['cleanup_confirmed'])
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0].url.path, '/v2/users/'+USER+'/messages')
        self.assertEqual(set(json.loads(self.posts[0].content)), {'msg_type', 'content'})
        self.assertEqual(load_recipient(self.bindings[0], APP)['user_openid'], USER)
        with self.assertRaises(BotError):self.manager.confirm(result['pairing_id'], snapshot['user_ref'])
        self.assertEqual(len(self.posts), 1)

    def test_group_text_and_unauthenticated_c2c_cannot_pair(self):
        result = self.start()
        gateway = self.manager._run.gateway
        gateway._dispatch(packet(result['challenge_command']))
        gateway._dispatch_authenticated(packet(result['challenge_command'], event='GROUP_AT_MESSAGE_CREATE'))
        self.assertIsNone(self.manager.status()['user_ref'])
        self.assertEqual(self.posts, [])

    def test_wrong_nonce_invalid_fields_stale_or_future_message_cannot_pair(self):
        now = datetime.now(timezone.utc)
        for change in ('wrong nonce', '', '\ud800'):
            self.assertIsNone(match_private_message(packet(change), '/绑定提醒 expected', now))
        good = packet('/绑定提醒 expected', observed=now)
        self.assertEqual(match_private_message(good, '/绑定提醒 expected', now), USER)
        for observed in (now - timedelta(seconds=60), now + timedelta(seconds=1)):
            self.assertIsNone(match_private_message(packet('/绑定提醒 expected', observed=observed), '/绑定提醒 expected', now))
        for key, value in (('id', '\n'), ('message_type', True), ('attachments', ['bad'])):
            bad = packet('/绑定提醒 expected', observed=now)
            bad['d'][key] = value
            self.assertIsNone(match_private_message(bad, '/绑定提醒 expected', now))

    def test_duplicates_and_other_sender_after_match_cannot_change_recipient(self):
        result = self.identify()
        first = self.manager.status()['user_ref']
        self.manager._run.gateway._dispatch_authenticated(packet(result['challenge_command'], user='different-user'))
        self.assertEqual(self.manager.status()['user_ref'], first)
        with self.assertRaises(BotError):self.manager.confirm(result['pairing_id'], 'wrong-ref')
        self.assertEqual(self.posts, [])

    def test_owner_conflict_fails_before_reading_secret_or_network(self):
        locks = self.root/'outputs/qq-bot/locks'
        locks.parent.mkdir(parents=True)
        ensure_private_directory(locks)
        with process_lock(locks/('bot-'+_hash([APP,GROUP])[:24]+'.lock')):
            with self.assertRaisesRegex(BotError, 'ALREADY_RUNNING'):
                self.manager.start(APP, GROUP, validate=lambda:None, bind=self.bindings.append)
        self.secret.assert_not_called()
        self.assertEqual(self.posts, [])

    def test_second_manager_same_app_conflicts_without_second_credential_read(self):
        self.start()
        other = self.make()
        self.addCleanup(other.close)
        before = self.secret.call_count
        with self.assertRaises(BotError):other.start(APP, 'different-group', validate=lambda:None, bind=self.bindings.append)
        self.assertEqual(self.secret.call_count, before)

    def test_unknown_delivery_is_never_retried_or_bound(self):
        result = self.identify()
        self.outcome = 'UNKNOWN'
        status = self.manager.confirm(result['pairing_id'], self.manager.status()['user_ref'])
        self.assertEqual(status['code'], 'QQ_DELIVERY_UNKNOWN')
        self.assertEqual(status['message_submissions'], 1)
        self.assertEqual(self.bindings, [])
        with self.assertRaises(BotError):self.manager.confirm(result['pairing_id'], status['user_ref'])
        self.assertEqual(len(self.posts), 1)

    def test_platform_denial_is_bounded_and_no_binding_written(self):
        result = self.identify()
        self.outcome = 'DENIED'
        status = self.manager.confirm(result['pairing_id'], self.manager.status()['user_ref'])
        self.assertEqual(status['code'], 'QQ_API_40034105')
        self.assertNotIn('not logged', json.dumps(status))
        self.assertEqual(self.bindings, [])

    def test_cancel_and_close_stop_worker_clear_nonce_and_release_owned_lock(self):
        result = self.start()
        status = self.manager.cancel(result['pairing_id'])
        self.assertEqual(status['phase'], 'CANCELLED')
        self.assertTrue(status['cleanup_confirmed'])
        self.assertFalse(self.manager._run.thread.is_alive())
        self.assertEqual(self.manager._run._challenge, '')
        self.assertEqual(self.posts, [])
        self.manager.close()

    def test_expiry_is_bounded_and_restart_has_no_memory(self):
        self.manager = self.make(seconds=1)
        self.addCleanup(self.manager.close)
        self.start()
        self.wait(lambda:self.manager.status()['cleanup_confirmed'])
        self.assertEqual(self.manager.status()['phase'], 'EXPIRED')
        self.assertEqual(self.make().status()['phase'], 'IDLE')

    def test_config_changed_before_confirmation_zero_message_post(self):
        result = self.identify()
        self.manager._run.validate = Mock(side_effect=BotError('QQ_SETTINGS_STALE'))
        with self.assertRaisesRegex(BotError, 'QQ_SETTINGS_STALE'):
            self.manager.confirm(result['pairing_id'], self.manager.status()['user_ref'])
        self.assertEqual(self.posts, [])

    def test_report_failure_after_api_acceptance_never_retries_or_binds(self):
        result = self.identify()
        with patch('apps.qq_bot.private_pairing._private_json', side_effect=OSError('sensitive')):
            status = self.manager.confirm(result['pairing_id'], self.manager.status()['user_ref'])
        self.assertTrue(status['api_accepted'])
        self.assertEqual(status['phase'], 'FAILED')
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.bindings, [])

    def test_gateway_heartbeats_continue_while_waiting_for_human_confirmation(self):
        self.identify()
        self.wait(lambda:any(frame['op'] == 1 for frame in self.socket.sent))
        self.assertEqual(self.manager.status()['phase'], 'AWAITING_CONFIRMATION')
        self.assertEqual(self.posts, [])

    def test_binding_failure_after_success_does_not_repeat_send(self):
        result = self.identify()
        self.manager._run.bind = Mock(side_effect=BotError('QQ_SETTINGS_CONFLICT'))
        status = self.manager.confirm(result['pairing_id'], self.manager.status()['user_ref'])
        self.assertEqual(status['phase'], 'FAILED')
        self.assertTrue(status['api_accepted'])
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.bindings, [])

    def test_cleanup_failure_quarantines_owner_and_refuses_another_pairing(self):
        self.start()
        run = self.manager._run
        original = run.api.close
        run.api.close = Mock(side_effect=OSError('not logged'))
        try:
            status = self.manager.cancel(run.id)
            self.assertEqual(status['code'], 'PRIVATE_PAIRING_CLEANUP_OR_REPORT_FAILED')
            self.assertFalse(status['cleanup_confirmed'])
            with self.assertRaises(BotError):self.manager.start(APP, GROUP, validate=lambda:None, bind=self.bindings.append)
        finally:
            # Test-only disposal of the synthetic held handle; production requires process restart.
            run.api.close = original
            original()
            run._owners.close()
            run.cleanup_confirmed = True


if __name__ == '__main__':unittest.main()
