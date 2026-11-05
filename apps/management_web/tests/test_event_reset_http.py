"""Explicit maintenance resets use synthetic state and the original local gate."""
import unittest

from apps.management_web.app import create_app
from apps.monitoring.tests import test_event_ack as fixture


class EventResetHTTPTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.EventAckTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.case.oxygen(4.2);self.case.ack()
        self.app=create_app(data_service=self.case.service)
        self.client=self.app.test_client()
        token=self.client.get('/api/bootstrap').json['event_management']['write_token']
        self.headers={'X-Management-Events':token,'Origin':'http://localhost'}

    def post(self,path,value,**kwargs):
        return self.client.post('/api/events/'+path,json=value,headers=self.headers,**kwargs)

    def test_reset_all_requires_local_token_then_clears_ack_and_keeps_water(self):
        original=self.case.repo.read('sim-pond-1','water')
        denied=self.client.post('/api/events/deletion-preview',json={'scope':'reset_all'})
        self.assertEqual(denied.status_code,403)
        remote=self.post('deletion-preview',{'scope':'reset_all'},environ_base={'REMOTE_ADDR':'192.168.1.100'})
        self.assertEqual(remote.status_code,403)
        preview=self.post('deletion-preview',{'scope':'reset_all'})
        self.assertEqual(preview.status_code,200)
        self.assertGreater(preview.json['count'],0);self.assertEqual(preview.json['ack_count'],1)
        self.assertTrue(self.case.service.events())  # Preview did not delete anything.
        result=self.post('delete',{'scope':'reset_all','revision':preview.json['revision']})
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.client.get('/api/bootstrap').json['events'],[])
        self.assertEqual(self.case.repo.read('sim-pond-1','water'),original)
        with self.case.repo.connection() as db:
            for table in ('events','alerts','event_actions','event_handling','event_handling_members'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_reset_cycle_stale_preview_refuses_and_fresh_preview_removes_whole_row(self):
        event=self.case.current()
        preview=self.post('deletion-preview',{'scope':'reset_cycle','event_id':event['id']})
        self.assertEqual(preview.status_code,200)
        self.case.oxygen(2.2)
        changed=self.post('delete',{'scope':'reset_cycle','event_id':event['id'],'revision':preview.json['revision']})
        self.assertEqual(changed.status_code,409)
        self.assertTrue(self.case.service.events())
        preview=self.post('deletion-preview',{'scope':'reset_cycle','event_id':event['id']})
        result=self.post('delete',{'scope':'reset_cycle','event_id':event['id'],'revision':preview.json['revision']})
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.case.service.events(),[])
        self.case.oxygen(2.2)
        new=self.case.service.events()
        self.assertTrue(new)
        self.assertNotIn(event['id'],[e['id'] for e in new])
