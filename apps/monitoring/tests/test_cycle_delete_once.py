"""One visible ended risk cycle must disappear in one explicit transaction."""
import json
from datetime import timedelta
import unittest
from unittest.mock import patch
from apps.management_web.app import create_app
from apps.monitoring.tests import test_event_ack as fixture


class CycleDeleteOnceTests(unittest.TestCase):
    setUp=fixture.EventAckTests.setUp
    batch=fixture.EventAckTests.batch
    oxygen=fixture.EventAckTests.oxygen
    water_events=fixture.EventAckTests.water_events
    current=fixture.EventAckTests.current
    request=fixture.EventAckTests.request
    ack=fixture.EventAckTests.ack

    def cycle(self,*,ack=False,end=True):
        self.oxygen(4.2)
        if ack:self.ack()
        self.oxygen(2.2)
        if ack:self.ack(self.current('OXYGEN_CRITICAL_LOW'))
        event=self.current('OXYGEN_CRITICAL_LOW')
        if end:self.oxygen(6.4)
        return event['id']

    def test_unacknowledged_two_grade_cycle_removed_with_one_delete_and_stays_gone(self):
        target=self.cycle();before=self.service.event_cycles()
        self.assertEqual(len(before),1);self.assertEqual(before[0]['cycle_summary']['count'],2)
        self.assertTrue(before[0]['can_delete_cycle'])
        with self.repo.connection() as db:
            business={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('current','history','batches','channel_contacts')}
        plan=self.repo.prepare_event_deletion('cycle',target)
        self.assertEqual((plan['count'],plan['ack_count']),(2,0))
        result=self.repo.delete_events('cycle',target,plan['revision'])
        self.assertEqual(result['deleted_count'],2);self.assertEqual(self.service.event_cycles(),[])
        with self.repo.connection() as db:
            for table,rows in business.items():self.assertEqual([tuple(r) for r in db.execute('SELECT * FROM '+table)],rows)
            self.assertEqual(list(db.execute('PRAGMA foreign_key_check')),[])
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)
        self.oxygen(6.4);self.assertEqual(self.service.event_cycles(),[])
        with self.assertRaisesRegex(ValueError,'EVENT_NOT_FOUND'):
            self.repo.delete_events('cycle',target,plan['revision'])

    def test_cycle_scope_keeps_ack_atomic_and_bulk_policy_unchanged(self):
        target=self.cycle(ack=True)
        self.assertEqual(self.repo.prepare_event_deletion('all_resolved')['count'],0)
        plan=self.repo.prepare_event_deletion('cycle',target);self.assertEqual(plan['ack_count'],2)
        self.assertEqual(self.repo.delete_events('cycle',target,plan['revision'])['deleted_ack_count'],2)
        with self.repo.connection() as db:
            for table in ('events','event_actions','event_handling','event_handling_members'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_active_unknown_and_manual_audit_never_deleted(self):
        target=self.cycle(end=False)
        for _ in range(2):
            self.assertFalse(self.service.event_cycles()[0]['can_delete_cycle'])
            with self.assertRaisesRegex(ValueError,'EVENT_CYCLE_NOT_ENDED'):
                self.repo.prepare_event_deletion('cycle',target)
            self.now+=timedelta(seconds=95)
        self.oxygen(6.4)
        with self.repo.connection() as db:
            row=json.loads(db.execute('SELECT payload FROM events WHERE id=?',(target,)).fetchone()[0])
            row['manual_ends']=[{'fixture':'audit'}]
            db.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(row),target))
        with self.assertRaisesRegex(ValueError,'EVENT_MANUAL_END_AUDIT_RETAINED'):
            self.repo.prepare_event_deletion('cycle',target)

    def test_revision_rollback_and_external_reference_protection(self):
        target=self.cycle(ack=True);plan=self.repo.prepare_event_deletion('cycle',target)
        with self.repo.connection() as db:db.execute('UPDATE event_handling SET revision=revision+1')
        with self.assertRaisesRegex(ValueError,'EVENT_DELETE_CONFLICT'):
            self.repo.delete_events('cycle',target,plan['revision'])
        plan=self.repo.prepare_event_deletion('cycle',target)
        with self.repo.connection() as db:
            db.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with self.assertRaisesRegex(ValueError,'EVENT_DELETE_STORAGE_ERROR'):
            self.repo.delete_events('cycle',target,plan['revision'])
        self.assertEqual(len(self.service.events()),2)
        with self.repo.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM event_actions').fetchone()[0],2)
            db.execute('DROP TRIGGER fail_delete')
            row=json.loads(db.execute('SELECT payload FROM events WHERE id=?',(target,)).fetchone()[0])
            row.update(id='external-reference',superseded_by=target);row.pop('risk_family')
            db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(row['id'],row['device_id'],row['channel'],row['code'],json.dumps(row)))
        with self.assertRaisesRegex(ValueError,'EVENT_CYCLE_REFERENCED'):
            self.repo.prepare_event_deletion('cycle',target)

    def test_other_cycles_and_legacy_without_reliable_identity_are_not_merged(self):
        target=self.cycle();plan=self.repo.prepare_event_deletion('cycle',target)
        self.oxygen(4.2);current=self.current()['id']
        self.repo.delete_events('cycle',target,plan['revision'])
        self.assertEqual([e['id'] for e in self.service.event_cycles()],[current])
        with self.repo.connection() as db:
            raw=json.loads(db.execute('SELECT payload FROM events WHERE id=?',(current,)).fetchone()[0])
            raw.pop('risk_family');raw.pop('rule_identity')
            db.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(raw),current))
        with self.assertRaisesRegex(ValueError,'EVENT_CYCLE_UNSUPPORTED'):
            self.repo.prepare_event_deletion('cycle',current)

    def test_same_episode_text_other_device_or_rule_scope_is_preserved(self):
        target=self.cycle()
        with self.repo.connection() as db:
            original=json.loads(db.execute('SELECT payload FROM events WHERE id=?',(target,)).fetchone()[0])
            for key in ('other-device','other-rule'):
                row=json.loads(json.dumps(original));row['id']=key
                row['risk_family']['transitions']=[]
                if key=='other-device':row['device_id']='sim-pond-2'
                else:row['rule_version']='synthetic-other-rule';row['rule_identity']['version']=row['rule_version']
                db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(row['id'],row['device_id'],row['channel'],row['code'],json.dumps(row)))
        plan=self.repo.prepare_event_deletion('cycle',target);self.assertEqual(plan['count'],2)
        self.repo.delete_events('cycle',target,plan['revision'])
        self.assertEqual({e['id'] for e in self.repo.events()},{'other-device','other-rule'})

    def test_unacknowledged_preview_conflicts_on_concurrent_member_change(self):
        target=self.cycle();plan=self.repo.prepare_event_deletion('cycle',target)
        with self.repo.connection() as db:
            row=json.loads(db.execute('SELECT payload FROM events WHERE id=?',(target,)).fetchone()[0])
            row['last_observed_at']=self.now.isoformat()
            row['fixture_revision']='changed'
            db.execute('UPDATE events SET payload=? WHERE id=?',(json.dumps(row),target))
        with self.assertRaisesRegex(ValueError,'EVENT_DELETE_CONFLICT'):
            self.repo.delete_events('cycle',target,plan['revision'])
        self.assertEqual(len(self.repo.events()),2)

    def test_http_cycle_preview_commit_counts_and_local_gate(self):
        target=self.cycle()
        with create_app(data_service=self.service).test_client() as client:
            token=client.get('/api/bootstrap').json['event_management']['write_token']
            headers={'X-Management-Events':token};body=dict(scope='cycle',event_id=target)
            self.assertEqual(client.post('/api/events/deletion-preview',json=body).status_code,403)
            preview=client.post('/api/events/deletion-preview',json=body,headers=headers)
            self.assertEqual(preview.status_code,200)
            self.assertEqual(preview.json['count'],2)
            commit=client.post('/api/events/delete',json={**body,'revision':preview.json['revision']},headers=headers)
            self.assertEqual(commit.status_code,200)
            self.assertEqual(client.get('/api/events?view=cycles').json['total'],0)
