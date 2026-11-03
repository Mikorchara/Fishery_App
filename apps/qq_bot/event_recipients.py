"""Local notification destination, prepared only from a successful active probe.

This config is a binding, not sending permission. A new process approval is still
required. No credentials, business reads, network or QQ/LLM authorization here.
"""
import argparse
import hashlib
import json
from pathlib import Path

from apps.ai_backend.secure_files import guard_path, inspect_policy, write_private
from apps.ai_service.runtime.release_contracts import _hash
from .configuration import app_identifier, json_object
from .contracts import BotError, identifier

CONTRACT = 'qq-private-event-recipient@1'
PROBE = 'qq-private-active-probe@1'


def read_private(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or str(path).startswith('\\\\'):
        raise BotError('EVENT_RECIPIENT_PATH_REJECTED')
    try:
        guard_path(path, regular=True); inspect_policy(path)
        with path.open('rb') as stream:
            return json_object(stream.read(16385), 16384)
    except Exception:
        raise BotError('EVENT_RECIPIENT_UNAVAILABLE') from None


def recipient_ref(app_id, user_id):
    return hashlib.sha256((app_id+'\0'+user_id).encode()).hexdigest()[:12]


def load_recipient(path, app_id):
    value = read_private(path)
    if (set(value) != {'contract', 'app_id', 'user_openid', 'user_ref', 'active_probe_sha256'}
            or value.get('contract') != CONTRACT or value.get('app_id') != app_id):
        raise BotError('EVENT_RECIPIENT_BINDING_INVALID')
    app_identifier(app_id); identifier(value['user_openid'])
    proof = value['active_probe_sha256']
    if (value['user_ref'] != recipient_ref(app_id, value['user_openid'])
            or type(proof) is not str or len(proof) != 64
            or any(c not in '0123456789abcdef' for c in proof)):
        raise BotError('EVENT_RECIPIENT_BINDING_INVALID')
    return value


def prepare_recipient(probe_directory, output):
    """Explicit create-only operation. Never scan/select recipients or overwrite."""
    directory, output = Path(probe_directory), Path(output)
    result = read_private(directory/'result.json')
    recipient = read_private(directory/'recipient.json')
    app = app_identifier(recipient.get('app_id')); user = identifier(recipient.get('user_openid'))
    ref = recipient_ref(app, user)
    if (result.get('contract') != PROBE or recipient.get('contract') != PROBE
            or result.get('mode') != 'active_once' or result.get('api_accepted') is not True
            or result.get('code') != 'QQ_PRIVATE_ACTIVE_API_ACCEPTED'
            or result.get('operator_approved_active') is not True
            or result.get('message_submissions') != 1 or result.get('proactive_messages') != 1
            or result.get('report_saved') is not True or result.get('recipient_saved') is not True
            or result.get('user_ref') != ref or recipient.get('user_ref') != ref
            or recipient.get('status') != 'PROBE_RECIPIENT_ONLY'
            or recipient.get('business_access') is not False):
        raise BotError('EVENT_RECIPIENT_ACTIVE_PROBE_REQUIRED')
    value = dict(contract=CONTRACT, app_id=app, user_openid=user, user_ref=ref,
                 active_probe_sha256=_hash([result, recipient]))
    if not output.is_absolute() or '..' in output.parts or str(output).startswith('\\\\'):
        raise BotError('EVENT_RECIPIENT_PATH_REJECTED')
    guard_path(output, regular=True)
    if output.exists(): raise BotError('EVENT_RECIPIENT_TARGET_EXISTS')
    write_private(output, (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode())
    return dict(code='EVENT_PRIVATE_RECIPIENT_PREPARED', user_ref=ref,
                network_requests=0, model_requests=0, sending_approved=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description='从已成功的主动私聊验证准备独立通知目标；不联网')
    parser.add_argument('--probe-directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_recipient(args.probe_directory, args.output)), flush=True)
        return 0
    except Exception as error:
        print(json.dumps(dict(code=error.code if isinstance(error, BotError)
                              else 'EVENT_RECIPIENT_PREPARATION_FAILED')), flush=True)
        return 1


if __name__ == '__main__': raise SystemExit(main())
