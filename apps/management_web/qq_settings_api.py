"""Local QQ settings remain available when the Web Assistant is disabled."""
from hmac import compare_digest
from ipaddress import ip_address
import json
from flask import jsonify, request
from apps.ai_service.qq_settings import QQSettingsError
from apps.ai_service.management_policy import _unique_object


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
        value = service.public() if request.method == 'GET' else service.save(body())
        return jsonify(**value, browser_token=service.browser_token)

    @app.post('/api/settings/qq/secret')
    def qq_secret():
        failure = checked()
        if failure is not None:
            return failure
        return jsonify(**service.save_secret(body()), browser_token=service.browser_token)

    @app.errorhandler(QQSettingsError)
    def qq_settings_error(error):
        return jsonify(error_code=error.code), 409
