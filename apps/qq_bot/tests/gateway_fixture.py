import json
GROUP, MEMBER = 'fictional-group', 'fictional-member'
def packet(content, now, *, msg_id='fixture-message', group=GROUP, member=MEMBER):
    return json.dumps({'op': 0, 't': 'GROUP_AT_MESSAGE_CREATE', 's': 1, 'd': {'id': msg_id, 'group_openid': group, 'author': {'member_openid': member, 'bot': False}, 'timestamp': now.isoformat(), 'content': content}}, ensure_ascii=False).encode('utf-8')
