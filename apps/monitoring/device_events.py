"""Device-report event adapter; no simulated batches, recovery or schema changes.

The receiver owns wire validation. This adapter consumes its persisted reports,
atomically storing the inbox cursor with event updates in Monitoring SQLite.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import uuid

from .contracts import identifier

CODE = 'DEVICE_REPORT_SIGNAL'
RULE_VERSION = 'device-report-presence-v1'
FRESH_SECONDS = 120


def stamp(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.utcoffset() is None:raise ValueError('DEVICE_REPORT_TIME_REQUIRED')
    return result.astimezone(timezone.utc)


def positive(report):
    return report.get('has_abnormality') is True or any(
        item.get('targets',0)>0 for item in report.get('abnormalities',[]))


def payload_from_row(row):
    if not row:return None
    value=row['payload']
    return json.loads(value) if isinstance(value,str) else value


def cursor(db,device_id):
    row=db.execute("SELECT payload FROM current WHERE device_id=? AND channel='visual'",(device_id,)).fetchone()
    payload=payload_from_row(row)
    return payload.get('inbox_cursor',0) if payload and payload.get('source_kind')=='device_report' else 0


def import_report(db,report,*,received_at,inbox_cursor,now):
    identifier(report['device_id']);identifier(report['report_id'])
    if type(inbox_cursor) is not int or inbox_cursor<1:raise ValueError('DEVICE_REPORT_CURSOR_INVALID')
    now,received=stamp(now),stamp(received_at)
    observed=stamp(report['window']['end'])
    device=report['device_id']
    rows=db.execute('SELECT * FROM current WHERE device_id=?',(device,)).fetchall()
    if any(payload_from_row(row).get('source_kind')!='device_report' for row in rows):
        raise ValueError('DEVICE_REPORT_DEVICE_CONFLICT')
    current=next((r for r in rows if r['channel']=='visual'),None)
    payload=payload_from_row(current)
    if payload and inbox_cursor<=payload.get('inbox_cursor',0):return dict(status='duplicate',event_id=None)
    if current and observed<stamp(current['observed_at']):
        payload['inbox_cursor']=inbox_cursor
        db.execute("UPDATE current SET payload=? WHERE device_id=? AND channel='visual'",(json.dumps(payload),device))
        return dict(status='out_of_order',event_id=None)
    envelope=dict(source_kind='device_report',device_report=report,inbox_cursor=inbox_cursor)
    db.execute('''INSERT INTO current VALUES(?,?,?,?,?,?) ON CONFLICT(device_id,channel) DO UPDATE SET
        batch_id=excluded.batch_id,observed_at=excluded.observed_at,received_at=excluded.received_at,payload=excluded.payload''',
        (device,'visual',report['report_id'],observed.isoformat(),received.isoformat(),json.dumps(envelope)))
    if not 0<=(now-observed).total_seconds()<=FRESH_SECONDS:return dict(status='stale',event_id=None)
    if not positive(report):return dict(status='no_signal',event_id=None)
    row=db.execute('''SELECT e.payload FROM alerts a JOIN events e ON e.id=a.event_id
        WHERE a.device_id=? AND a.channel='visual' AND a.code=?''',(device,CODE)).fetchone()
    event=json.loads(row['payload']) if row else None
    if event and event.get('source_kind')!='device_report':raise ValueError('DEVICE_REPORT_EVENT_CONFLICT')
    rule=dict(rule_id=CODE,version=RULE_VERSION,scope=['device_report','visual','window_report','non_diagnostic'],
        publication_status='PROTOTYPE',assessment_policy_version=RULE_VERSION)
    observation=dict(device_id=device,channel='visual',batch_id=report['report_id'],source_kind='device_report',
        observed_at=observed.isoformat(),received_at=received.isoformat(),window_start=report['window']['start'],
        window_end=report['window']['end'],window_duration_s=report['window']['duration_s'],aggregation='window_report')
    if event is None:
        event=dict(id=uuid.uuid4().hex,device=device,device_id=device,channel='visual',code=CODE,
            type='设备视觉信号',occurred_at=observed.isoformat(),received_at=received.isoformat(),
            batch_id=report['report_id'],attachments=[])
    event.update(source_kind='device_report',title='设备视觉异常报告（需核查）',
        description='设备模型报告的检测信号；不是疾病确诊，未执行设备操作。',
        severity='warning',finding_severity='warning',status='pending',lifecycle_state='ACTIVE',state_reason=None,
        publication_status='PROTOTYPE',rule_version=RULE_VERSION,rule_identity=rule,observation=observation,
        last_observed_at=observed.isoformat(),last_batch_id=report['report_id'],assessed_at=now.isoformat(),
        device_report=deepcopy(report))
    db.execute('''INSERT INTO events VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload''',
        (event['id'],device,'visual',CODE,json.dumps(event)))
    db.execute('''INSERT INTO alerts VALUES(?,?,?,?) ON CONFLICT(device_id,channel,code) DO UPDATE SET event_id=excluded.event_id''',
        (device,'visual',CODE,event['id']))
    return dict(status='accepted',event_id=event['id'])


def project(event,row,now):
    """Recent positive report proves a reported signal, never sensor online/health."""
    result=deepcopy(event);now=stamp(now)
    payload=payload_from_row(row)
    report=payload.get('device_report') if payload and payload.get('source_kind')=='device_report' else None
    observed=stamp(report['window']['end']) if report else None
    age=(now-observed).total_seconds() if observed else None
    freshness='fresh' if age is not None and 0<=age<=FRESH_SECONDS else 'stale' if age is not None and age>FRESH_SECONDS else 'unknown'
    active=bool(report and positive(report) and freshness=='fresh'
        and stamp(report['window']['end'])>=stamp(event['last_observed_at']))
    result.update(lifecycle_state='ACTIVE' if active else 'INDETERMINATE',status='pending',
        state_reason=None if active else 'DEVICE_REPORT_STALE' if freshness=='stale' else 'DEVICE_REPORT_CURRENT_SIGNAL_UNCONFIRMED',
        evaluated_at=now.isoformat(),current_data_quality=dict(quality='valid' if report else 'missing',
            freshness=freshness,connectivity='unknown'))
    return result
