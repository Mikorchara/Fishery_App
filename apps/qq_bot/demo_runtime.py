"""Finite local Fake Gateway and memory SDK; never a live fallback."""
from datetime import datetime, timezone
import json
import time
import httpx
from openai import AsyncOpenAI


def provider_factory(runtime, remaining):
    async def handle(request):
        body = json.loads(request.content)
        tool = next((m for m in body['messages'] if m['role'] == 'tool'), None)
        if tool is None:
            message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'demo-call',
                'type': 'function', 'function': {'name': 'get_current_water_quality', 'arguments': '{}'}}]}
            reason = 'tool_calls'
        else:
            payload = json.loads(tool['content'])
            hits = [f['code'] for f in payload.get('findings', []) if f['state'] == 'HIT' and f['kind'] == 'WATER_RISK']
            dq = payload['data_quality']
            limited = payload['status'] != 'OK' or (dq['quality'], dq['freshness'], dq['connectivity']) != ('valid','fresh','online')
            plan = dict(contract='qq-water-explanation@1', source='simulator', context='limited' if limited else 'window',
                metrics=['temperature_c','ph','dissolved_oxygen_mg_l'], rules=hits,
                advice=['verify_observation', 'review_rules' if hits else 'check_reporting' if limited else 'continue_observation'])
            message = {'role': 'assistant', 'content': json.dumps(dict(contract='qq-hybrid-reply@2',kind='water',plan=plan))}
            reason = 'stop'
        return httpx.Response(200, json={'id':'demo', 'object':'chat.completion','created':0,'model':runtime.model,
            'choices':[{'index':0,'message':message,'finish_reason':reason}],
            'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30}})
    return AsyncOpenAI(api_key='fictional-only',base_url=runtime.base_url,max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle),trust_env=False,follow_redirects=False))


class FakeSocket:
    """Authenticated fake READY then one synthetic member question, with real pump/worker."""
    def __init__(self, app, group, member):
        self.socket = self
        self.frames = [{'op':10,'d':{'heartbeat_interval':1000}},
            {'op':0,'s':1,'t':'READY','d':{'session_id':'m3-demo','user':{'id':'demo-bot'},'application':{'id':app}}},
            {'op':0,'s':2,'t':'GROUP_AT_MESSAGE_CREATE','d':{'id':'m3-demo-message','group_openid':group,
              'author':{'member_openid':member,'bot':False},'timestamp':datetime.now(timezone.utc).isoformat(),
              'content':'现在水质怎么样？'}}]
        self.closed = False
    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    def send(self, raw):
        if json.loads(raw)['op'] == 1: self.frames.append({'op':11})
    def recv(self, timeout):
        if self.closed: raise OSError('fake closed')
        if self.frames: return json.dumps(self.frames.pop(0))
        time.sleep(min(timeout,.05)); raise TimeoutError()
    def shutdown(self,*_): self.closed=True
    def close(self): self.closed=True


def qq_client():
    def handle(request):
        if request.url.path == '/app/getAppAccessToken':
            return httpx.Response(200,json={'access_token':'fictional-only','expires_in':3600})
        if request.url.path == '/gateway':
            return httpx.Response(200,json={'url':'wss://api.bot.qq.com/websocket/'})
        return httpx.Response(200,json={'id':'fake-accepted'})
    return httpx.Client(transport=httpx.MockTransport(handle),trust_env=False,follow_redirects=False)
