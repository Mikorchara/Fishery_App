"""Local QQ settings remain available when the Web Assistant is disabled."""
from hmac import compare_digest
from ipaddress import ip_address
import json
from flask import jsonify, request
from apps.ai_service.qq_settings import QQSettingsError
from apps.ai_service.management_policy import _unique_object
from apps.ai_service.runtime.release_contracts import _hash


def _browser_settings(value):
    """Give the browser references, while preserving real identities on the server."""
    settings = value['settings']
    return {
        **value,
        'settings': {key: setting for key, setting in settings.items()
                     if key not in ('app_id', 'group_id', 'members')},
        'identity': {
            'app_ref': _hash(settings['app_id'])[:12] if settings['app_id'] else None,
            'group_ref': _hash(settings['group_id'])[:12] if settings['group_id'] else None,
            'member_refs': [_hash(member)[:12] for member in settings['members']],
        },
    }


def _restore_unchanged_identity(service, value):
    if not isinstance(value, dict) or not isinstance(value.get('settings'), dict):
        return value
    settings = value['settings']
    app_blank = settings.get('app_id') == ''
    pair_blank = settings.get('group_id') == '' and settings.get('members') == []
    if not (app_blank or pair_blank):
        return value
    current = service.public()
    previous = current['settings']
    if value.get('revision') != current['revision'] or not previous['app_id']:
        return value
    # The service checks this same revision again under the write lock.
    settings = dict(settings)
    if app_blank:
        settings['app_id'] = previous['app_id']
    if pair_blank and settings.get('app_id') == previous['app_id']:
        settings.update(group_id=previous['group_id'], members=previous['members'])
    return {**value, 'settings': settings}


def register_qq_settings_api(app, service):
    def body():
        try:
            return json.loads(request.get_data(cache=False), object_pairs_hook=_unique_object,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
        except (ValueError, TypeError, RecursionError):
            raise QQSettingsError('QQ_SETTINGS_JSON_INVALID') from None

    def checked():
        try:
            local = ip_address(request.remote_addr or '').is_loopback
        except ValueError:
            local = False
        if not local:
            return jsonify(error_code='QQ_SETTINGS_LOCAL_ONLY'), 403
        if service is None:
            return jsonify(error_code='QQ_SETTINGS_NOT_CONNECTED'), 503
        if request.method == 'POST':
            token = request.headers.get('X-Management-QQ', '')
            if not token.isascii() or not compare_digest(token, service.browser_token):
                return jsonify(error_code='QQ_SETTINGS_ACCESS_DENIED'), 403
            if request.mimetype != 'application/json':
                return jsonify(error_code='QQ_SETTINGS_JSON_REQUIRED'), 400

    @app.get('/api/settings/qq')
    @app.post('/api/settings/qq')
    def qq_settings():
        failure = checked()
        if failure is not None:
            return failure
        value = (service.public() if request.method == 'GET'
                 else service.save(_restore_unchanged_identity(service, body())))
        return jsonify(**_browser_settings(value), browser_token=service.browser_token)

    @app.post('/api/settings/qq/secret')
    def qq_secret():
        failure = checked()
        if failure is not None:
            return failure
        return jsonify(**_browser_settings(service.save_secret(body())), browser_token=service.browser_token)

    @app.get('/api/settings/qq/pairing')
    def qq_pairing_status():
        failure = checked()
        if failure is not None:
            return failure
        return jsonify(pairing=service.pairing_status())

    @app.post('/api/settings/qq/pairing/start')
    @app.post('/api/settings/qq/pairing/confirm')
    @app.post('/api/settings/qq/pairing/cancel')
    def qq_pairing_action():
        failure = checked()
        if failure is not None:
            return failure
        value = body()
        if request.path.endswith('/start'):
            result = service.pairing_start(value)
        else:
            result = service.pairing_action(value, confirm=request.path.endswith('/confirm'))
        return jsonify(pairing=result)

    @app.errorhandler(QQSettingsError)
    def qq_settings_error(error):
        return jsonify(error_code=error.code), 409
