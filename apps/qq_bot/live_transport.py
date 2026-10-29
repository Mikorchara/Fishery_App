"""Only an in-process Management permit can create real QQ HTTPS/WSS I/O."""
import logging
from threading import RLock, Event
import httpx
from apps.ai_service.channel_management_live import LivePermit
from .transport import QQAPI, gateway_url, GATEWAY_CLOSE_SECONDS
from .configuration import app_identifier
from .contracts import BotError


def check_live_gateway(gateway, coordinator=None):
    if type(gateway) is not LiveQQTransport: return False
    gateway.permit.check()
    if coordinator is not None and getattr(coordinator.session_run, 'permit', None) is not gateway.permit:
        raise BotError('MANAGEMENT_DELIVERY_PERMIT_MISMATCH')
    return True


class LiveQQAPI(QQAPI):
    def __init__(self, app_id, secret, *, permit, client=None, monotonic=None):
        import time
        if type(permit) is not LivePermit: raise BotError('MANAGEMENT_RUN_PERMIT_REQUIRED')
        permit.check()
        if permit.offline != (client is not None): raise BotError('MANAGEMENT_QQ_IO_MODE_MISMATCH')
        if client is not None and (type(client) is not httpx.Client or type(client._transport) is not httpx.MockTransport):
            raise BotError('MANAGEMENT_QQ_MEMORY_HTTP_REQUIRED')
        self.app_id, self.permit = app_identifier(app_id), permit
        self._secret, self._now = secret, monotonic or time.monotonic
        self._client = client or httpx.Client(timeout=httpx.Timeout(10, connect=5),
            trust_env=False, follow_redirects=False)
        self._owned = client is None
        self._token, self._expires, self._token_lock = None, 0, RLock()

    def _request(self, *args, before_post=None, **kwargs):
        self.permit.check()
        def validate():
            self.permit.check()
            if before_post: before_post()
        return super()._request(*args, before_post=validate, **kwargs)


class LiveQQTransport:
    def __init__(self, api, host):
        if type(api) is not LiveQQAPI or api.permit is not host.permit or api.app_id != host.access.app_id:
            raise BotError('MANAGEMENT_QQ_COMPOSITION_REQUIRED')
        self.api, self.host, self.permit = api, host, host.permit
        self._connected, self._closed = Event(), Event()

    @property
    def connected(self): return self._connected.is_set() and not self._closed.is_set()
    def reconnect(self):
        self.permit.check()
        if not self._closed.is_set(): self._connected.set()
    def disconnect(self): self._connected.clear()
    def close(self): self._closed.set(); self.api.close()
    def send(self, context, reply, *, clock, cancelled, before_post):
        def validate():
            self.permit.check()
            if cancelled.is_set() or not self.connected: raise BotError('AI_GATEWAY_DISCONNECTED')
            before_post()
        validate()
        return self.api.reply(reply, received_at=context.timestamp, now=clock(), before_post=validate)


def live_connector(permit):
    if type(permit) is not LivePermit or permit.offline:
        raise BotError('MANAGEMENT_NETWORK_PERMIT_REQUIRED')
    def connect(url):
        permit.check()
        from websockets.sync.client import connect as websocket_connect
        logger = logging.Logger('fishery.qq.wire.disabled', logging.CRITICAL+1)
        logger.addHandler(logging.NullHandler())
        return websocket_connect(gateway_url(url), proxy=None, compression=None,
            open_timeout=10, close_timeout=GATEWAY_CLOSE_SECONDS, max_size=65536,
            max_queue=4, ping_interval=None, logger=logger)
    return connect
