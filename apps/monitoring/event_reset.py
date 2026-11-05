"""Explicit local maintenance: remove event records, never observation data.

Unlike ordinary history cleanup, the operator may select an unfinished cycle or
all statuses. The preview revision covers evidence, links and ACK records; the
Repository owns the transaction and keeps foreign keys enabled throughout.
"""
import json

from .event_handling import cycle_reference, digest
from .event_records import EventRecordError, validate_delete

SCOPES = ('reset_cycle', 'reset_all')


def _rows(db, table, order):
    return [dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY '+order)]


def _prepare(db, scope, event_id):
    validate_delete(scope, event_id)
    if scope not in SCOPES:raise EventRecordError('INVALID_EVENT_DELETE')
    rows=_rows(db,'events','id')
    raw={row['id']:row for row in rows}
    events={key:json.loads(row['payload']) for key,row in raw.items()}
    handling=_rows(db,'event_handling','cycle_id')
    actions=_rows(db,'event_actions','id')
    members=_rows(db,'event_handling_members','event_id')
    alerts=_rows(db,'alerts','device_id,channel,code,event_id')
    if scope=='reset_all':
        selected=set(events);cycles={row['cycle_id'] for row in handling}
        affected_handling,affected_actions,affected_members,affected_alerts=handling,actions,members,alerts
    else:
        if event_id not in events:raise EventRecordError('EVENT_NOT_FOUND',404)
        selected={event_id};cycles=set()
        context=(raw[event_id]['device_id'],raw[event_id]['channel'])
        while True:
            previous=(set(selected),set(cycles))
            references={cycle_reference(events[key]) for key in selected}
            references.discard(None)
            selected.update(key for key,event in events.items() if cycle_reference(event) in references)
            cycles.update(row['cycle_id'] for row in handling if row['anchor_event_id'] in selected)
            cycles.update(row['cycle_id'] for row in [*actions,*members] if row['event_id'] in selected)
            selected.update(row['anchor_event_id'] for row in handling if row['cycle_id'] in cycles)
            selected.update(row['event_id'] for row in [*actions,*members] if row['cycle_id'] in cycles)
            if any(key not in raw or (raw[key]['device_id'],raw[key]['channel'])!=context for key in selected):
                # Corrupt cross-device audit relationships cannot make deleting a
                # single cycle erase another device. The explicit all-reset can
                # still remove that entire malformed event set in one operation.
                raise EventRecordError('EVENT_RESET_CROSS_DEVICE_REFERENCE',409)
            if previous==(selected,cycles):break
        affected_handling=[row for row in handling if row['cycle_id'] in cycles]
        affected_actions=[row for row in actions if row['cycle_id'] in cycles]
        affected_members=[row for row in members if row['cycle_id'] in cycles]
        affected_alerts=[row for row in alerts if row['event_id'] in selected]
    candidates=[row for row in rows if row['id'] in selected]
    detached=[row for row in rows if row['id'] not in selected
              and events[row['id']].get('superseded_by') in selected]
    manual={action.get('request_id') or digest(action) for key in selected
            for action in events[key].get('manual_ends',[])}
    state=dict(candidates=candidates,handling=affected_handling,actions=affected_actions,
               members=affected_members,alerts=affected_alerts,detached=detached)
    preview=dict(scope=scope,event_id=event_id,count=len(candidates),ack_count=len(affected_actions),
        manual_end_count=len(manual),active_count=sum(events[key].get('status')!='closed'
            and events[key].get('lifecycle_state')!='RESOLVED' for key in selected),
        legacy_count=sum(cycle_reference(events[key]) is None for key in selected),
        detached_reference_count=len(detached),revision=digest([scope,event_id,state]))
    return state,preview


def deletion_plan(db, scope, event_id):
    state,preview=_prepare(db,scope,event_id)
    return state['candidates'],preview


def delete_records(db, scope, event_id, revision):
    state,preview=_prepare(db,scope,event_id)
    if preview['revision']!=revision:raise EventRecordError('EVENT_DELETE_CONFLICT',409)
    if scope=='reset_all':
        for table in ('event_actions','event_handling_members','event_handling','alerts','events'):
            db.execute('DELETE FROM '+table)
    else:
        for row in state['actions']:db.execute('DELETE FROM event_actions WHERE id=?',(row['id'],))
        for row in state['members']:db.execute('DELETE FROM event_handling_members WHERE event_id=?',(row['event_id'],))
        for row in state['handling']:db.execute('DELETE FROM event_handling WHERE cycle_id=?',(row['cycle_id'],))
        for row in state['alerts']:
            db.execute('DELETE FROM alerts WHERE device_id=? AND channel=? AND code=? AND event_id=?',
                       tuple(row[key] for key in ('device_id','channel','code','event_id')))
        for row in state['detached']:
            event=json.loads(row['payload']);event.pop('superseded_by',None)
            db.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(event),row['id']))
        for row in state['candidates']:db.execute('DELETE FROM events WHERE id=?',(row['id'],))
    return dict(scope=scope,deleted_count=preview['count'],deleted_ack_count=preview['ack_count'],
        deleted_manual_end_count=preview['manual_end_count'],
        detached_reference_count=preview['detached_reference_count'])
