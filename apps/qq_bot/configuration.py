"""Strict local access config only; M2 never composes or reads credentials."""
import json
from pathlib import Path
import re

from apps.ai_backend import secure_files
from .contracts import BotConfig, GroupAccess, BotError, _object, _constant



def app_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{5,32}', value):
        raise BotError('INVALID_QQ_APP_ID')
    return value


def json_object(raw, limit=65536):
    try:
        if not isinstance(raw, (str, bytes)):
            raise BotError('INVALID_PACKET')
        body = raw.encode('utf-8') if isinstance(raw, str) else raw
        if not 0 < len(body) <= limit:
            raise BotError('PACKET_SIZE_LIMIT')
        value = json.loads(body.decode('utf-8'), object_pairs_hook=_object, parse_constant=_constant)
        if not isinstance(value, dict):
            raise BotError('INVALID_PACKET')
        return value
    except BotError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise BotError('INVALID_PACKET') from None


def load_access(path):
    try:
        path = Path(path).absolute()
        secure_files.guard_path(path, regular=True)
        with path.open('rb') as stream:
            value = json_object(stream.read(16385), 16384)
        if (set(value) != {'schema_version', 'app_id', 'groups'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or not isinstance(value['groups'], list) or not 1 <= len(value['groups']) <= 16):
            raise BotError('INVALID_ACCESS_CONFIG')
        groups = []
        for item in value['groups']:
            if (not isinstance(item, dict) or set(item) != {'group_id', 'device_id', 'members', 'capabilities'}
                    or not isinstance(item['members'], list) or not isinstance(item['capabilities'], list)):
                raise BotError('INVALID_ACCESS_CONFIG')
            groups.append(GroupAccess(item['group_id'], item['device_id'], tuple(item['members']), tuple(item['capabilities'])))
        return BotConfig(app_identifier(value['app_id']), tuple(groups))
    except BotError:
        raise
    except Exception:
        raise BotError('ACCESS_CONFIG_UNAVAILABLE') from None

