"""Explicit event-only reset uses synthetic SQLite and never user instances."""
from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
import unittest
import uuid

from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.tests import test_event_ack as ack_fixture
from apps.monitoring.tests import test_device_events as device_fixture


class EventResetTests(unittest.TestCase):
    setUp=ack_fixture.EventAckTests.setUp
    batch=ack_fixture.EventAckTests.batch
    ingest=ack_fixture.EventAckTests.ingest
    oxygen=ack_fixture.EventAckTests.oxygen
    water_events=ack_fixture.EventAckTests.water_events
    current=ack_fixture.EventAckTests.current
    request=ack_fixture.EventAckTests.request
    ack=ack_fixture.EventAckTests.ack

    def reset(self,scope='reset_all',event_id=None):
        preview=self.repo.prepare_event_deletion(scope,event_id)
        return self.repo.delete_events(scope,event_id,preview['revision'])

    def observation_rows(self):
        with self.repo.connection() as db:
            return {table:[tuple(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid')]
                    for table in ('batches','history','current','channel_contacts')}

    def board(self,number=1):
        report=device_fixture.DeviceEventTests.report(self,number)
        return self.repo.import_device_report(report,received_at=self.now,inbox_cursor=number,now=self.now)

    def test_reset_all_removes_every_event_status_ack_and_manual_history_only(self):
        self.oxygen(4.2);self.ack();self.oxygen(2.2);self.ack(self.current('OXYGEN_CRITICAL_LOW'))
        self.oxygen(6.4)
        self.ingest('suspected_lesion');self.ack(self.current('SUSPECTED_LESION'))
        self.now+=timedelta(seconds=91)
        visual=self.current('SUSPECTED_LESION')
        preview=self.service.preview_manual_end(visual['id'])
        self.service.manual_end_event(dict(event_id=visual['id'],revision=preview['revision'],
            request_id=str(uuid.uuid4()),reason='清理前的合成人工结束记录'))
        self.board()
        legacy=deepcopy(self.repo.events()[0]);legacy.update(id='legacy-unknown',code='OLD_UNSUPPORTED',
            device_id='legacy-device',device='legacy-device',status='pending')
        for key in ('lifecycle_state','risk_family','handling','manual_ends'):legacy.pop(key,None)
        with self.repo.connection() as db:
            db.execute('INSERT INTO events VALUES(?,?,?,?,?)',
                (legacy['id'],legacy['device_id'],legacy['channel'],legacy['code'],json.dumps(legacy)))
        before=self.observation_rows()
        plan=self.repo.prepare_event_deletion('reset_all')
        self.assertGreaterEqual(plan['count'],4)
        self.assertEqual(plan['ack_count'],3)
        self.assertEqual(plan['manual_end_count'],1)
        self.assertGreaterEqual(plan['active_count'],2)
        self.assertEqual(plan['legacy_count'],1)
        result=self.repo.delete_events('reset_all',None,plan['revision'])
        self.assertEqual(result['deleted_count'],plan['count'])
        self.assertEqual(result['deleted_ack_count'],3)
        self.assertEqual(self.service.events(),[])
        self.assertEqual(before,self.observation_rows())
        self.assertEqual(self.repo.device_report_cursor('board-1'),1)
        with self.repo.connection() as db:
            for table in ('events','alerts','event_actions','event_handling','event_handling_members'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],2)

    def test_reset_selected_entire_cycle_preserves_other_device_and_other_cycle(self):
        self.oxygen(4.2);self.ack();original=self.current()
        self.oxygen(2.2);self.ack(self.current('OXYGEN_CRITICAL_LOW'))
        self.oxygen(4.2,device='sim-pond-2')
        other=next(e for e in self.water_events() if e['device_id']=='sim-pond-2')
        self.ack(other);self.board()
        before={e['id']:e for e in self.repo.events() if e['device_id']!='sim-pond-1'}
        preview=self.repo.prepare_event_deletion('reset_cycle',original['id'])
        self.assertEqual(preview['count'],2);self.assertEqual(preview['ack_count'],2)
        self.repo.delete_events('reset_cycle',original['id'],preview['revision'])
        after={e['id']:e for e in self.repo.events()}
        self.assertEqual(set(before),set(after))
        self.assertEqual(before,after)
        with self.repo.connection() as db:
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_current_observation_is_not_replayed_and_next_new_hit_starts_new_cycle(self):
        self.oxygen(4.2);self.ack();old=self.current();self.board()
        old_board=next(e for e in self.repo.events() if e['source_kind']=='device_report')
        self.reset()
        self.assertEqual(self.service.events(),[])
        self.assertEqual(self.board()['status'],'duplicate')
        self.assertEqual(self.service.events(),[])
        self.oxygen(4.2)
        new=self.current()
        self.assertNotEqual(old['id'],new['id'])
        self.assertNotEqual(old['risk_family']['episode_id'],new['risk_family']['episode_id'])
        self.assertEqual(new['handling']['action_count'],0)
        self.now+=timedelta(seconds=60);self.board(2)
        new_board=next(e for e in self.repo.events() if e['source_kind']=='device_report')
        self.assertNotEqual(old_board['id'],new_board['id'])

    def test_new_hit_and_ack_after_preview_are_conflicts(self):
        self.oxygen(4.2);event=self.current()
        preview=self.repo.prepare_event_deletion('reset_cycle',event['id'])
        self.oxygen(4.1)
        with self.assertRaisesRegex(Exception,'EVENT_DELETE_CONFLICT'):
            self.repo.delete_events('reset_cycle',event['id'],preview['revision'])
        preview=self.repo.prepare_event_deletion('reset_all')
        self.ack()
        with self.assertRaisesRegex(Exception,'EVENT_DELETE_CONFLICT'):
            self.repo.delete_events('reset_all',None,preview['revision'])
        self.assertEqual(len(self.water_events()),1)
        self.assertEqual(self.current()['handling']['action_count'],1)

    def test_legacy_record_and_outside_display_reference_can_be_removed(self):
        self.oxygen(4.2);event=self.current()
        external=deepcopy(event);external.update(id='legacy-reference',code='UNSUPPORTED_OLD',
            device_id='sim-pond-2',device='sim-pond-2',superseded_by=event['id'])
        for key in ('risk_family','handling'):external.pop(key,None)
        with self.repo.connection() as db:
            db.execute('INSERT INTO events VALUES(?,?,?,?,?)',
                (external['id'],external['device_id'],external['channel'],external['code'],json.dumps(external)))
        preview=self.repo.prepare_event_deletion('reset_cycle',event['id'])
        self.assertEqual(preview['count'],1)
        self.assertEqual(preview['detached_reference_count'],1)
        self.repo.delete_events('reset_cycle',event['id'],preview['revision'])
        remaining=self.repo.events()[0]
        self.assertEqual(remaining['id'],'legacy-reference')
        self.assertEqual(remaining['observation'],external['observation'])
        self.assertNotIn('superseded_by',remaining)
        self.assertEqual(self.reset('reset_cycle',remaining['id'])['deleted_count'],1)
        self.assertEqual(self.repo.events(),[])

    def test_event_delete_failure_rolls_back_alerts_ack_and_links(self):
        self.oxygen(4.2);self.ack()
        before=self.repo.events()
        plan=self.repo.prepare_event_deletion('reset_all')
        with self.repo.connection() as db:
            db.execute("CREATE TRIGGER prevent_reset BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'synthetic failure');END")
        with self.assertRaisesRegex(Exception,'EVENT_DELETE_STORAGE_ERROR'):
            self.repo.delete_events('reset_all',None,plan['revision'])
        self.assertEqual(before,self.repo.events())
        with self.repo.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM alerts').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM event_actions').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_empty_reset_and_readonly_refusal(self):
        self.assertEqual(self.reset()['deleted_count'],0)
        self.oxygen(4.2)
        readonly=MonitoringRepository(self.path.resolve(),read_only=True)
        plan=readonly.prepare_event_deletion('reset_all')
        with self.assertRaisesRegex(Exception,'EVENT_DELETE_STORAGE_ERROR'):
            readonly.delete_events('reset_all',None,plan['revision'])
        self.assertEqual(len(self.water_events()),1)


if __name__=='__main__':unittest.main()
