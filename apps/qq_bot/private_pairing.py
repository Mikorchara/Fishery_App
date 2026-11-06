"""Explicit, short-lived Web pairing; no AI, business reads or ordinary chat logging."""
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import secrets
import threading
import time
import uuid

import httpx
from apps.ai_backend.secure_files import write_private
from apps.ai_service.runtime.release_contracts import _hash
from .configuration import app_identifier
from .contracts import BotError, identifier, utc
from .event_recipients import PROBE, prepare_recipient, recipient_ref
from .gateway import QQGateway
from .management_config import ensure_private_directory, process_lock
from .transport import QQAPI, gateway_url, GATEWAY_CLOSE_SECONDS

PAIRING_SECONDS = 180
ACTIVE_TEXT = '主动消息测试：鳗鲡养殖智能体的 Management 私聊通知连接验证。本条不调用模型，也不代表发生了真实异常。'
_SEAL = object()


def _safe_code(error):
    code = getattr(error, 'code', '')
    return code if isinstance(code, str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,80}', code) else 'PRIVATE_PAIRING_FAILED'


def _private_json(path, value):
    write_private(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


@contextmanager
def _quiet_wire():
    """Suppress only this request thread's HTTP diagnostics, not other Web logging."""
    thread = threading.get_ident()
    class Filter(logging.Filter):
        def filter(self, record):
            return not (record.thread == thread and record.name.startswith(('httpx', 'httpcore')))
    guard = Filter()
    loggers = [logging.getLogger('httpx'), logging.getLogger('httpcore')]
    loggers.extend(value for key, value in list(logging.Logger.manager.loggerDict.items())
                   if key.startswith(('httpx.', 'httpcore.')) and isinstance(value, logging.Logger))
    handlers = list(logging.getLogger().handlers)
    for item in [*loggers, *handlers]:item.addFilter(guard)
    try:
        yield
    finally:
        for item in [*loggers, *handlers]:item.removeFilter(guard)


def match_private_message(packet, challenge, now):
    """Same C2C fields as the previously verified probe; keep only one matched sender."""
    if type(packet) is not dict or packet.get('t') != 'C2C_MESSAGE_CREATE' or type(packet.get('op')) is not int or packet['op'] != 0:
        return None
    data = packet.get('d')
    if type(data) is not dict or type(data.get('message_type', 0)) is not int or data.get('message_type', 0) != 0:
        return None
    if any(data.get(k) for k in ('attachments', 'ark_data', 'msg_elements')):
        return None
    author, content = data.get('author'), data.get('content')
    if (type(author) is not dict or author.get('bot', False) is not False or type(content) is not str
            or len(content) > 128):
        return None
    try:
        if not secrets.compare_digest(content.strip().encode(), challenge.encode()):
            return None
        stamp = data['timestamp']
        if type(stamp) is not str or len(stamp) > 64:
            return None
        observed = utc(datetime.fromisoformat(stamp.replace('Z', '+00:00')))
        if not 0 <= (utc(now) - observed).total_seconds() < 60:
            return None
        message_id = data['id']  # C2C ID is opaque; it is never used as a path/header or sent back.
        if (type(message_id) is not str or not 1 <= len(message_id.encode('utf-8')) <= 4096
                or any(not c.isprintable() or c.isspace() for c in message_id)):
            return None
        return identifier(author['user_openid'])
    except (KeyError, ValueError, TypeError, OverflowError, UnicodeError):
        return None


class _PairingAPI(QQAPI):
    """Reuse the existing official HTTPS/token/error boundary under a pairing-only permit."""
    def __init__(self, pairing, secret, *, client=None, seal=None):
        if seal is not _SEAL:
            raise BotError('PRIVATE_PAIRING_APPROVAL_REQUIRED')
        pairing.check()
        if client is not None and (type(client) is not httpx.Client or type(client._transport) is not httpx.MockTransport):
            raise BotError('PRIVATE_PAIRING_MEMORY_HTTP_REQUIRED')
        self.pairing, self.app_id, self._secret = pairing, pairing.app_id, secret
        self._now = pairing.monotonic
        if client is None:
            # A private logger avoids wire/body output without muting unrelated Web traffic.
            client = httpx.Client(timeout=httpx.Timeout(10, connect=5), trust_env=False, follow_redirects=False)
            self._owned = True
        else:
            self._owned = False
        self._client, self._token, self._expires = client, None, 0
        self._token_lock = threading.RLock()

    def _request(self, *args, before_post=None, **kwargs):
        self.pairing.check()
        def validate():
            self.pairing.check()
            if before_post:
                before_post()
        with _quiet_wire():
            return super()._request(*args, before_post=validate, **kwargs)

    def active_once(self):
        def claim():
            with self.pairing.lock:
                self.pairing.check()
                if not self.pairing.gateway.ready.is_set() or self.pairing.gateway.stop.is_set():
                    raise BotError('PRIVATE_PAIRING_GATEWAY_DISCONNECTED')
                if self.pairing.submissions:
                    raise BotError('PRIVATE_PAIRING_ALREADY_SUBMITTED')
                self.pairing.submissions = 1  # Claim before HTTP; failed/unknown is never retried.
        result = self._request('POST', '/v2/users/' + identifier(self.pairing._user) + '/messages',
            body=dict(msg_type=0, content=ACTIVE_TEXT), before_post=claim)
        if not isinstance(result.get('id'), str) or not result['id']:
            raise BotError('QQ_SEND_NOT_CONFIRMED')


class _PairingGateway(QQGateway):
    def __init__(self, pairing, api, **options):
        self.pairing = pairing
        super().__init__(pairing.app_id, api, discover=lambda *_: None, **options)

    def _dispatch(self, packet):
        # Authentication comes from the original READY/Resume lifecycle, never from packet JSON.
        if not self.ready.is_set() or not getattr(self._dispatch_context, 'authenticated', False):
            return
        user = match_private_message(packet, self.pairing._challenge, self.clock())
        if user is not None:
            self.pairing.offer(user)


def _connector(pairing):
    def connect(url):
        pairing.check()
        from websockets.sync.client import connect as websocket_connect
        logger = logging.Logger('fishery.qq.pairing.wire.disabled', logging.CRITICAL + 1)
        logger.addHandler(logging.NullHandler())
        return websocket_connect(gateway_url(url), proxy=None, compression=None, open_timeout=10,
            close_timeout=GATEWAY_CLOSE_SECONDS, max_size=65536, max_queue=4, ping_interval=None, logger=logger)
    return connect


class PrivatePairing:
    def __init__(self, manager, app_id, group_id, *, validate, bind, secret_supplier, client=None, connector=None):
        self.manager, self.app_id, self.group_id = manager, app_identifier(app_id), identifier(group_id)
        self.id = uuid.uuid4().hex
        self.lock, self.cancelled, self._send_done = threading.RLock(), threading.Event(), threading.Event()
        self._send_done.set()
        self.monotonic, self.clock = manager.monotonic, manager.clock
        self.expires = self.monotonic() + manager.seconds
        self.validate, self.bind, self._secret_supplier = validate, bind, secret_supplier
        self.client, self.connector = client, connector
        self._challenge = '/绑定提醒 ' + secrets.token_hex(16)
        self._user = self.user_ref = None
        self.phase, self.code = 'CONNECTING', 'PRIVATE_PAIRING_CONNECTING'
        self.submissions, self.api_accepted, self.cleanup_confirmed = 0, False, False
        self.gateway = self.api = self.thread = None
        self._owners = ExitStack()
        self.directory = manager.config_directory.parent / '.qq-private-pairings' / ('pair-' + self.id)

    def __repr__(self):
        return 'PrivatePairing(<redacted>)'

    def check(self):
        if self.cancelled.is_set():
            raise BotError('PRIVATE_PAIRING_CANCELLED')
        if self.monotonic() >= self.expires:
            raise BotError('PRIVATE_PAIRING_EXPIRED')
        self.validate()

    def offer(self, user):
        with self.lock:
            if self.phase not in ('CONNECTING', 'WAITING_PRIVATE_MESSAGE') or self.cancelled.is_set():
                return
            try:
                self.check()
            except Exception:
                return
            self._user = user
            self.user_ref = recipient_ref(self.app_id, user)
            self.phase, self.code = 'AWAITING_CONFIRMATION', 'PRIVATE_PAIRING_CONFIRM_RECIPIENT'
            self._challenge = ''  # The matched nonce cannot be reused by another sender.

    def public(self):
        with self.lock:
            return dict(pairing_id=self.id, phase=self.phase, code=self.code, user_ref=self.user_ref,
                seconds_remaining=max(0, int(self.expires - self.monotonic())), message_submissions=self.submissions,
                api_accepted=self.api_accepted, client_display_confirmed=False, cleanup_confirmed=self.cleanup_confirmed,
                model_requests=0, business_queries=0)

    def start(self):
        try:
            locks = self.manager.project_root / 'outputs' / 'qq-bot' / 'locks'
            locks.parent.mkdir(parents=True, exist_ok=True)
            ensure_private_directory(locks)
            key = _hash([self.app_id, self.group_id])[:24]
            # Same lock as Management Bot, plus one app-level pairing owner across Web instances.
            self._owners.enter_context(process_lock(locks / ('bot-' + key + '.lock')))
            self._owners.enter_context(process_lock(locks / ('pairing-app-' + self.app_id + '.lock')))
            parent = self.directory.parent
            parent.parent.mkdir(parents=True, exist_ok=True)
            ensure_private_directory(parent)
            ensure_private_directory(self.directory)
            self.api = _PairingAPI(self, self._secret_supplier, client=self.client, seal=_SEAL)
            self.gateway = _PairingGateway(self, self.api, connector=self.connector or _connector(self),
                clock=self.clock, monotonic=self.monotonic, emit=self._event)
            self.thread = threading.Thread(target=self._run, name='management-qq-pairing')
            self.thread.start()
        except Exception:
            if self.api is not None:
                self.api.close()
            self._owners.close()
            self.cleanup_confirmed = True
            raise

    def _event(self, code, **_):
        with self.lock:
            if code == 'QQ_GATEWAY_READY' and self.phase == 'CONNECTING':
                self.phase, self.code = 'WAITING_PRIVATE_MESSAGE', 'PRIVATE_PAIRING_SEND_CHALLENGE'

    def _run(self):
        try:
            self.gateway.run(self.manager.seconds, max_seconds=self.manager.seconds)
        except Exception as error:
            with self.lock:
                if self.phase != 'BOUND':
                    self.phase, self.code = 'FAILED', _safe_code(error)
        finally:
            # A confirmation POST runs on its own HTTP handler, never on the heartbeat thread.
            if not self._send_done.wait(12):
                with self.lock:
                    self.phase, self.code = 'FAILED', 'PRIVATE_PAIRING_CLEANUP_FAILED'
                return  # Retain ownership; no new Bot/pairing may claim unconfirmed resources.
            try:
                self.api.close()
                with self.lock:
                    if self.phase not in ('BOUND', 'FAILED', 'CANCELLED'):
                        self.phase, self.code = 'EXPIRED', 'PRIVATE_PAIRING_EXPIRED'
                    self._user, self._challenge = None, ''
                self._owners.close()
                self.cleanup_confirmed = True
                _private_json(self.directory/'status.json', self.public())
            except Exception:
                with self.lock:
                    self.phase, self.code = 'FAILED', 'PRIVATE_PAIRING_CLEANUP_OR_REPORT_FAILED'

    def confirm(self, user_ref):
        with self.lock:
            self.check()
            if self.phase != 'AWAITING_CONFIRMATION' or not isinstance(user_ref, str) or user_ref != self.user_ref:
                raise BotError('PRIVATE_PAIRING_CONFIRMATION_INVALID')
            self.phase, self.code = 'SENDING_TEST', 'PRIVATE_PAIRING_TEST_IN_PROGRESS'
            self._send_done.clear()
        try:
            self.api.active_once()
            self.api_accepted = True
            self.check()
            if not self.gateway.ready.is_set() or self.gateway.stop.is_set():
                raise BotError('PRIVATE_PAIRING_GATEWAY_DISCONNECTED')
            recipient = dict(contract=PROBE, app_id=self.app_id, user_openid=self._user, user_ref=self.user_ref,
                status='PROBE_RECIPIENT_ONLY', business_access=False)
            result = dict(contract=PROBE, mode='active_once', code='QQ_PRIVATE_ACTIVE_API_ACCEPTED',
                api_accepted=True, operator_approved_active=True, message_submissions=1, proactive_messages=1,
                report_saved=True, recipient_saved=True, user_ref=self.user_ref)
            _private_json(self.directory/'recipient.json', recipient)
            _private_json(self.directory/'result.json', result)
            target = self.manager.config_directory / ('event-recipient-' + self.id + '.json')
            prepare_recipient(self.directory, target)
            self.check()
            self.bind(target)
            with self.lock:
                self.phase, self.code = 'BOUND', 'PRIVATE_PAIRING_BOUND_NOTIFICATIONS_DISABLED'
        except Exception as error:
            with self.lock:
                self.phase, self.code = 'FAILED', _safe_code(error)
        finally:
            self._send_done.set()
            self.gateway.request_stop()
            self.thread.join(5)
        return self.public()

    def cancel(self):
        with self.lock:
            self.cancelled.set()
            if self.phase not in ('BOUND', 'FAILED', 'EXPIRED'):
                self.phase, self.code = 'CANCELLED', 'PRIVATE_PAIRING_CANCELLED'
            self._challenge = ''
        if self.gateway is not None:
            self.gateway.request_stop()
        if self.thread is not None:
            self.thread.join(5)
        return self.public()


class PairingManager:
    def __init__(self, project_root, config_directory, *, secret_supplier, seconds=PAIRING_SECONDS,
                 client=None, connector=None, monotonic=time.monotonic, clock=None):
        if type(seconds) is not int or not 1 <= seconds <= PAIRING_SECONDS:
            raise BotError('PRIVATE_PAIRING_DURATION_INVALID')
        self.project_root, self.config_directory = Path(project_root), Path(config_directory)
        self.secret_supplier, self.seconds = secret_supplier, seconds
        self.client, self.connector, self.monotonic = client, connector, monotonic
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._run, self._lock = None, threading.RLock()

    def start(self, app_id, group_id, *, validate, bind):
        with self._lock:
            if self._run is not None and not self._run.cleanup_confirmed:
                raise BotError('PRIVATE_PAIRING_ALREADY_RUNNING_OR_CLEANUP_FAILED')
            run = PrivatePairing(self, app_id, group_id, validate=validate, bind=bind,
                secret_supplier=self.secret_supplier, client=self.client, connector=self.connector)
            run.start()
            self._run = run
            return dict(run.public(), challenge_command=run._challenge)

    def status(self):
        with self._lock:
            return self._run.public() if self._run is not None else dict(phase='IDLE', code='PRIVATE_PAIRING_IDLE')

    def selected(self, pairing_id):
        with self._lock:
            if self._run is None or type(pairing_id) is not str or pairing_id != self._run.id:
                raise BotError('PRIVATE_PAIRING_NOT_FOUND')
            return self._run

    def confirm(self, pairing_id, user_ref):
        return self.selected(pairing_id).confirm(user_ref)

    def cancel(self, pairing_id):
        return self.selected(pairing_id).cancel()

    def close(self):
        with self._lock:
            run = self._run
        if run is not None and not run.cleanup_confirmed:
            run.cancel()
