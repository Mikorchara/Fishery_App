"""Rule-event notices, separate from AI and passive replies. No model or DB writes."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import threading
import time

from apps.ai_backend.secure_files import exclusive_lock, guard_path
from apps.ai_service.runtime.release_contracts import _hash
from apps.monitoring.event_handling import cycle_reference, RANKS
from apps.monitoring.event_records import parse_time
from .contracts import BotError
from .service import plain

CONTRACT = 'qq-rule-event-notifications@1'
MAX_BYTES = 1024 * 1024
MAX_CLAIMS = 2000
DAILY_LIMIT = 100
INTERVAL_SECONDS = 10
POLL_SECONDS = 5
QUALITY_CODES = frozenset(('SENSOR_INVALID','SENSOR_PARTIAL','SENSOR_MISSING','SENSOR_STALE','DEVICE_OFFLINE'))


def approval_summary(recipient=None,device_id=None):
    result=dict(contract=CONTRACT, enabled=True, events=['new','upgrade','resolved'],
        interval_seconds=INTERVAL_SECONDS, poll_seconds=POLL_SECONDS,daily_limit=DAILY_LIMIT, model_requests=0,
        retries=0, destination='VERIFIED_PRIVATE_RECIPIENT_ONLY' if recipient else 'CURRENT_CONFIGURED_GROUP_ONLY',
        **({'recipient_ref':recipient['user_ref'],'recipient_sha256':_hash(recipient)} if recipient else {}), source='SIMULATOR',
        permission='OPERATOR_APPROVAL_AND_QQ_PLATFORM_PERMISSION', lifetime='THIS_BOT_PROCESS',replay_history=False)
    if device_id is not None:
        result.update(sources=['SIMULATOR','DEVICE_REPORT'],device_report_device_id=device_id,
            device_report_events=['new'],device_report_recovery=False)
    return result


class NotificationPermit:
    """Internal reference, never parsed from chat or a saved approval JSON."""
    def __init__(self, host):
        from .management_run import ManagementRun
        recipient = getattr(host, '_notice_recipient', None)
        device_id=getattr(host,'device_event_device_id',None)
        if type(host) is not ManagementRun or host.plan().get('event_notifications')!=approval_summary(recipient,device_id):
            raise BotError('EVENT_NOTIFICATION_APPROVAL_REQUIRED')
        host.check()
        group=next(g for g in host.access.groups if g.group_id==host.inputs.group_id)
        if ('current' if recipient else 'events') not in group.capabilities:raise BotError('EVENT_NOTIFICATION_PERMISSION_REQUIRED')
        self.host=host;self.group_id=group.group_id;self.device_id=host.device_id
        self._authorization=host.permit
        self.recipient = recipient
        self.device_event_device_id=device_id
        self.recipient_path = getattr(host, '_notice_recipient_path', None)
        self.audience=_hash([host.access.app_id,self.group_id,host.monitoring.binding_revision,self.device_id,
            *([recipient['user_ref']] if recipient else [])])

    def __repr__(self):return 'NotificationPermit(<local-approved-binding>)'

    def check(self):
        host=self.host
        if host.permit is not self._authorization:raise BotError('EVENT_NOTIFICATION_APPROVAL_CHANGED')
        if (getattr(host,'device_event_device_id',None)!=self.device_event_device_id
                or host.plan().get('event_notifications')!=approval_summary(self.recipient,self.device_event_device_id)):
            raise BotError('EVENT_NOTIFICATION_APPROVAL_CHANGED')
        if self.recipient:
            from .event_recipients import load_recipient
            if load_recipient(self.recipient_path,host.access.app_id)!=self.recipient:
                raise BotError('EVENT_NOTIFICATION_RECIPIENT_CHANGED')
        try:host.check()
        except BotError as error:
            if error.code!='RUN_EXPIRED' or not host.plan().get('keep_online_after_ai_expiry'):raise
            host.check_fixed_only()
        audience=_hash([host.access.app_id,host.inputs.group_id,host.monitoring.binding_revision,host.device_id,
                *([self.recipient['user_ref']] if self.recipient else [])])
        if self.audience!=audience:
            raise BotError('EVENT_NOTIFICATION_BINDING_CHANGED')


class NoticeJournal:
    """Small append-only attempt journal; claim is durable before any POST.

    Existing/unknown attempts are never retried, including after restart. Local
    OS-user tampering is outside the trust boundary. Full or damaged logs fail closed.
    """
    def __init__(self, directory, audience, *, clock):
        if len(audience)!=64 or any(c not in '0123456789abcdef' for c in audience):
            raise BotError('EVENT_NOTIFICATION_BINDING_CHANGED')
        self.clock=clock;self.path=Path(directory)/(audience+'.jsonl')
        guard_path(Path(directory));guard_path(self.path,regular=True)
        self._guard=exclusive_lock(Path(directory)/(audience+'.lock'))
        self._guard.__enter__();self._stream=None;self.claims={};self.states={};self._last=None
        try:
            self._bytes=self.path.read_bytes() if self.path.exists() else b''
            if len(self._bytes)>MAX_BYTES:raise ValueError()
            for line in self._bytes.splitlines():
                value=json.loads(line)
                if (set(value)!={'contract','key','state','at'} or value['contract']!=CONTRACT
                        or len(value['key'])!=64 or any(c not in '0123456789abcdef' for c in value['key'])
                        or value['state'] not in ('CLAIMED','ACCEPTED','UNKNOWN','FAILED')
                        or parse_time(value['at']) is None):raise ValueError()
                key=value['key']
                if value['state']=='CLAIMED':
                    if key in self.claims:raise ValueError()
                    self.claims[key]=value['at']
                elif key not in self.claims or self.states.get(key)!='CLAIMED':raise ValueError()
                self.states[key]=value['state']
                stamp=parse_time(value['at'])
                if self._last is not None and stamp<self._last:raise ValueError()
                self._last=stamp
            if len(self.claims)>MAX_CLAIMS:raise ValueError()
            self._stream=self.path.open('r+b' if self.path.exists() else 'x+b')
        except Exception:
            self.close();raise BotError('EVENT_NOTIFICATION_JOURNAL_INVALID') from None

    def check(self):
        guard_path(self.path,regular=True)
        if self._stream is None or self.path.read_bytes()!=self._bytes:
            raise BotError('EVENT_NOTIFICATION_JOURNAL_CHANGED')
        stat=self.path.stat();current=os.fstat(self._stream.fileno())
        if (stat.st_dev,stat.st_ino)!=(current.st_dev,current.st_ino):
            raise BotError('EVENT_NOTIFICATION_JOURNAL_CHANGED')

    def _append(self,key,state):
        self.check();stamp=self.clock()
        if self._last is not None and stamp<self._last:raise BotError('EVENT_NOTIFICATION_CLOCK_ROLLBACK')
        data=(json.dumps(dict(contract=CONTRACT,key=key,state=state,at=stamp.isoformat()),sort_keys=True)+'\n').encode()
        if len(self._bytes)+len(data)>MAX_BYTES:raise BotError('EVENT_NOTIFICATION_JOURNAL_FULL')
        try:
            self._stream.seek(0,os.SEEK_END)
            if self._stream.write(data)!=len(data):raise OSError()
            self._stream.flush();os.fsync(self._stream.fileno());self._bytes+=data;self._last=stamp
        except Exception:raise BotError('EVENT_NOTIFICATION_JOURNAL_FAILED') from None
        self.states[key]=state

    def claim(self,key):
        self.check()
        if key in self.claims:return False
        if len(self.claims)>=MAX_CLAIMS:raise BotError('EVENT_NOTIFICATION_JOURNAL_FULL')
        today=self.clock().astimezone(timezone(timedelta(hours=8))).date()
        count=sum(parse_time(v).astimezone(timezone(timedelta(hours=8))).date()==today for v in self.claims.values())
        if count>=DAILY_LIMIT:raise BotError('EVENT_NOTIFICATION_DAILY_LIMIT')
        self._append(key,'CLAIMED');self.claims[key]=self._last.isoformat();return True

    def finish(self,key,state):self._append(key,state)

    def close(self):
        if self._stream is not None:self._stream.close();self._stream=None
        if self._guard is not None:
            self._guard.__exit__(None,None,None);self._guard=None


def candidate(event, *, device_id, source_kind='simulator'):
    """Only stable current cycles; no inferred legacy groups, ACK or manual closure."""
    if (event.get('device_id')!=device_id or event.get('source_kind')!=source_kind
            or not cycle_reference(event) or event.get('manual_end',{}).get('active')):return None
    state=event.get('lifecycle_state');key=(event.get('cycle_summary') or {}).get('key')
    if not key or key!=cycle_reference(event)[0]:return None
    if source_kind=='device_report':
        history=event.get('manual_end',{}).get('history',[])
        if history:
            key=_hash([key,'device-reopened-attention',history[-1]['request_id']])
    if state=='ACTIVE' and event.get('state_reason') is None and not event.get('superseded_by'):
        dq=event.get('current_data_quality',{})
        # A current quality/offline rule HIT is evidence of that quality problem,
        # never evidence that an old water-risk reading is still current.
        if source_kind=='device_report':
            # The existing device approval covers a fresh visual finding. The
            # versioned appearance event replaces that finding for peak reports.
            if (event.get('code') not in ('DEVICE_REPORT_SIGNAL','DEVICE_REPORT_APPEARANCE') or dq.get('freshness')!='fresh'
                    or dq.get('quality')!='valid'):return None
        elif event.get('code') not in QUALITY_CODES and (dq.get('freshness')!='fresh' or dq.get('connectivity')!='online'):return None
        transitions=(event.get('risk_family') or {}).get('transitions',[])
        stamp=transitions[-1].get('observed_at') if transitions else event.get('occurred_at')
        return key,'ACTIVE',RANKS.get(event.get('code'),0),stamp
    if source_kind=='simulator' and state=='RESOLVED' and event.get('status')=='closed' and parse_time(event.get('resolved_at')):
        return key,'RESOLVED',0,event['resolved_at']
    return None


def render(event, kind):
    title={'new':'新异常','upgrade':'异常等级升级','resolved':'规则条件已消退'}[kind]
    device=event.get('source_kind')=='device_report'
    lines=[f'鳗鲡养殖智能体 · {title}', ('DEVICE REPORT 设备检测信号 · ' if device else 'SIMULATOR 模拟信号 · ')+plain(event['device_id'],80),
        plain(event.get('title','异常信号'),160).replace('<','＜').replace('>','＞')+' · '+
        ('历史最高等级：' if kind=='resolved' else '')+
        {'critical':'严重','warning':'提醒','info':'提示'}.get(event.get('severity'),'待核实')]
    at=event.get('resolved_at') if kind=='resolved' else event.get('last_observed_at')
    parsed=parse_time(at)
    lines.append(('规则消退观测：' if kind=='resolved' else '事件观测时间：')+
        (parsed.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S 北京时间') if parsed else '未知'))
    lines.append('周期：'+plain(event['cycle_summary']['key'][:12],12))
    if device:
        for signal in event.get('device_report',{}).get('abnormalities',[])[:3]:
            label=plain(signal.get('name',signal.get('label','未提供类别')),60).replace('<','＜').replace('>','＞')
            lines.append('报告标签：'+label+' · '+str(signal.get('targets',0))+' 个目标')
        lines.append('设备模型报告的异常信号，需人工核查；未判定疾病确诊或恢复。')
    lines.append('可靠观测已满足该规则的消退条件；不代表治愈或人工处理完成。' if kind=='resolved'
        else '请到管理网页查看详情并核查；疑似疾病信号不是确诊，未执行设备操作。')
    return '\n'.join(lines)


class EventNotifier:
    def __init__(self,permit,api,journal,*,connected,clock,monotonic=time.monotonic,emit=lambda *_a,**_k:None):
        if type(permit) is not NotificationPermit:raise BotError('EVENT_NOTIFICATION_APPROVAL_REQUIRED')
        permit.check();self.permit,self.api,self.journal=permit,api,journal
        self.connected,self.clock,self.now,self.emit=connected,clock,monotonic,emit
        self._seen={};self._last_send=None;self._stop=threading.Event();self._thread=None
        self.code=None;self.accepted=0;self.unknown=0

    def validate(self):
        if self._stop.is_set() or not self.connected():raise BotError('EVENT_NOTIFICATION_DISCONNECTED')
        self.permit.check();self.journal.check()

    def tick(self):
        if not self.connected():return
        self.validate()
        events=self.permit.host.monitoring.event_cycles(device_id=self.permit.device_id)
        if self.permit.device_event_device_id is not None:
            events+=self.permit.host.monitoring.notification_event_cycles(
                device_id=self.permit.device_event_device_id,approved_device_id=self.permit.device_event_device_id)
        if len(events)>512:raise BotError('EVENT_NOTIFICATION_QUERY_LIMIT')
        if self._last_send is not None and self.now()-self._last_send<INTERVAL_SECONDS:return
        for event in sorted(events,key=lambda e:RANKS.get(e.get('code'),0),reverse=True):
            is_device=event.get('source_kind')=='device_report'
            item=candidate(event,device_id=self.permit.device_event_device_id if is_device else self.permit.device_id,
                source_kind='device_report' if is_device else 'simulator')
            if item is None:continue
            key,state,rank,stamp=item;previous=self._seen.get(key)
            if len(self._seen)>=512 and key not in self._seen:raise BotError('EVENT_NOTIFICATION_QUERY_LIMIT')
            if state=='RESOLVED' and (previous is None or previous[0]!='ACTIVE'):continue
            if state=='ACTIVE' and previous is not None and previous[0]=='ACTIVE' and rank<=previous[1]:
                self._seen[key]=(state,rank);continue
            message_key=_hash([self.permit.audience,key,state,rank,stamp])
            kind='resolved' if state=='RESOLVED' else 'upgrade' if previous else 'new'
            # A pending/unknown claim survives restart. Never replay a historical send.
            if not self.journal.claim(message_key):
                self._seen[key]=(state,rank);continue
            self._seen[key]=(state,rank);self._last_send=self.now()
            try:self.api.send_event_notice(self.permit,render(event,kind),before_post=self.validate)
            except BotError as error:
                unknown=error.code in ('QQ_DELIVERY_UNKNOWN','QQ_SEND_NOT_CONFIRMED','QQ_HTTP_UNAVAILABLE','QQ_RESPONSE_TOO_LARGE','INVALID_PACKET')
                if unknown:self.unknown+=1
                self.journal.finish(message_key,'UNKNOWN' if unknown else 'FAILED')
                raise
            # Preserve the known platform acceptance even if local persistence fails.
            # The durable CLAIMED record still forbids another POST after restart.
            self.accepted+=1;self.emit('QQ_EVENT_NOTICE_API_ACCEPTED')
            self.journal.finish(message_key,'ACCEPTED');return

    def start(self):
        if self._thread is not None:raise BotError('EVENT_NOTIFICATION_ALREADY_STARTED')
        def work():
            try:
                while not self._stop.wait(POLL_SECONDS):self.tick()
            except Exception as error:
                self.code=getattr(error,'code','EVENT_NOTIFICATION_FAILED')
                self.emit(self.code)
                self.emit('QQ_EVENT_NOTIFICATIONS_HALTED')
        self._thread=threading.Thread(target=work,name='qq-rule-event-notifications',daemon=False);self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(12)
            if self._thread.is_alive():raise BotError('EVENT_NOTIFICATION_STOP_FAILED')
        self.journal.close()

    def report(self):
        return dict(contract=CONTRACT,enabled=True,accepted=self.accepted,delivery_unknown=self.unknown,
            destination='private' if self.permit.recipient else 'group',
            recipient_ref=self.permit.recipient['user_ref'] if self.permit.recipient else None,
            state='HALTED' if self.code else 'CLOSED' if self._stop.is_set() else 'RUNNING',
            stop_code=self.code,client_display_confirmed=False,model_requests=0,automatic_retry=False)
