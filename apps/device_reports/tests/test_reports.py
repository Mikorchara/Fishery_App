"""Isolated synthetic reports only, no credentials, device or external network."""
import copy
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import io
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from apps.device_reports.__main__ import create_receiver,main
from apps.device_reports.contracts import ReportError,validate
from apps.device_reports.storage import ReportStore
from apps.management_web.app import create_app
from apps.monitoring.repository import MonitoringRepository
from apps.monitoring.service import MonitoringService
from apps.simulator.generator import Simulator
from apps.monitoring.contracts import validate_batch
from scripts.dev.local_session import commands

NOW=datetime(2026,10,31,0,0,tzinfo=timezone.utc)
DEVICE='synthetic-orin-1'
TOKEN='fictionaldevicetoken01234567890123456789'


def report():
    return dict(schema_version=1,report_id='sample-1',device_id=DEVICE,sent_at=NOW.isoformat(),
        window=dict(start=(NOW-timedelta(seconds=39)).isoformat(),end=NOW.isoformat(),duration_s=38,frames_processed=3),
        has_abnormality=True,report_text='<script>untrusted report, not instructions</script>',
        detection=dict(unique_tracks=2,avg_per_frame=2.,max_per_frame=2,avg_confidence=.81),
        abnormalities=[dict(label='body_ulceration',name='疑似病灶信号',targets=1,count=1,avg_confidence=.71,last_bbox=[150,95,90,50])],
        behavior=None,measurement=None)


def raw(value=None):return json.dumps(report() if value is None else value).encode()


class DeviceReportTests(unittest.TestCase):
    def setUp(self):
        t=TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.store=ReportStore.initialize(self.root/'reports')
        self.client=create_receiver(self.store,device_id=DEVICE,token=TOKEN,clock=lambda:NOW).test_client()

    def send(self,data=None,**kwargs):
        return self.client.post('/api/fish/reports',data=raw() if data is None else data,
            content_type='application/json; charset=utf-8',headers={'X-Device-Token':TOKEN},**kwargs)

    def test_durable_ack_duplicate_conflict_restart_and_old_report_order(self):
        self.assertEqual(self.send().json['status'],'accepted')
        self.assertEqual(self.send().json['status'],'duplicate')
        changed=report();changed['report_text']='changed'
        self.assertEqual(self.send(raw(changed)).status_code,409)
        old=report();old['report_id']='backfill';old['window']['start']=(NOW-timedelta(days=1,seconds=39)).isoformat();old['window']['end']=(NOW-timedelta(days=1)).isoformat()
        self.assertEqual(self.send(raw(old)).status_code,200)
        restored=ReportStore(self.root/'reports',read_only=True)
        rows=restored.recent(DEVICE,now=NOW)['items']
        self.assertEqual([x['report']['report_id'] for x in rows],['sample-1','backfill'])
        self.assertEqual(rows[1]['freshness'],'stale')
        self.assertEqual(rows[0]['warnings'],['WINDOW_DURATION_MISMATCH'])
        self.assertIsNone(rows[0]['report']['behavior'])
        self.assertEqual(restored.recent('other-device',now=NOW)['items'],[])
        with self.assertRaisesRegex(ReportError,'READ_ONLY'):restored.receive(raw(),device_id=DEVICE,now=NOW)
        with closing(sqlite3.connect(self.store.path)) as db:self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_auth_origin_size_version_types_and_missing_fields(self):
        self.assertEqual(self.client.post('/api/fish/reports',data=raw(),content_type='application/json').status_code,403)
        self.assertEqual(self.send(environ_overrides={'HTTP_ORIGIN':'http://evil.invalid'}).status_code,403)
        self.assertEqual(self.send(b' '*16385).status_code,413)
        self.assertEqual(self.client.get('/api/settings').status_code,404)
        cases=[]
        for field,value in [('schema_version',2),('device_id','other-device'),('behavior',0),('has_abnormality',1),('report_text','')]:
            v=report();v[field]=value;cases.append(v)
        v=report();v['window']['frames_processed']=True;cases.append(v)
        v=report();del v['window'];cases.append(v)
        for value in cases:self.assertGreaterEqual(self.send(raw(value)).status_code,400)
        self.assertEqual(self.send(b'{"schema_version":1,"schema_version":1}').status_code,400)
        self.assertEqual(self.send(b'{"x":NaN}').status_code,400)
        v=report();v['sent_at']=(NOW+timedelta(seconds=1)).isoformat()
        self.assertEqual(self.send(raw(v)).status_code,400)

    def test_explicit_token_free_receiver_preserves_report_and_admission_boundaries(self):
        client=create_receiver(self.store,device_id=DEVICE,require_token=False,clock=lambda:NOW).test_client()
        def send(value=None,**kwargs):
            return client.post('/api/fish/reports',data=raw(value),content_type='application/json',**kwargs)
        self.assertEqual(send().json['status'],'accepted')
        self.assertEqual(send().json['status'],'duplicate')
        other=report();other['device_id']='unbound-device';other['report_id']='unbound-report'
        self.assertGreaterEqual(send(other).status_code,400)
        self.assertEqual(send(headers={'Origin':'http://untrusted.invalid'}).status_code,403)
        self.assertEqual(client.get('/api/fish/reports').status_code,404)
        self.assertEqual(client.post('/api/fish/reports',data=raw(),content_type='text/plain').status_code,400)
        self.assertEqual(client.post('/api/fish/reports',data=b' '*16385,content_type='application/json').status_code,413)
        self.assertEqual(len(self.store.recent(DEVICE,now=NOW)['items']),1)
        # A fresh admission bucket makes the existing rolling limit deterministic.
        rate_client=create_receiver(self.store,device_id=DEVICE,require_token=False,clock=lambda:NOW).test_client()
        with patch('apps.device_reports.__main__.monotonic',return_value=100.):
            for _ in range(60):
                self.assertEqual(rate_client.post('/api/fish/reports',data=raw(),content_type='application/json').status_code,200)
            self.assertEqual(rate_client.post('/api/fish/reports',data=raw(),content_type='application/json').status_code,429)

    def test_token_required_remains_the_direct_receiver_default(self):
        with self.assertRaisesRegex(ReportError,'DEVICE_REPORT_TOKEN_REQUIRED'):
            create_receiver(self.store,device_id=DEVICE,clock=lambda:NOW)
        for headers in ({},{'X-Device-Token':'wrong-but-valid-token-01234567890123456789'}):
            response=self.client.post('/api/fish/reports',data=raw(),content_type='application/json',headers=headers)
            self.assertEqual(response.status_code,403)
        self.assertEqual(self.store.recent(DEVICE,now=NOW)['items'],[])

    def test_cli_default_token_mode_still_rejects_missing_token_before_opening_store(self):
        with (patch('apps.device_reports.__main__.os.environ',{}),
              patch('apps.device_reports.__main__.ReportStore',side_effect=AssertionError('no store without required token')),
              patch('werkzeug.serving.make_server',side_effect=AssertionError('must not listen')),
              patch('sys.stdout',new=io.StringIO()) as output):
            self.assertEqual(main(['--directory',str(self.root/'reports'),'--device-id',DEVICE,'--serve']),1)
        self.assertEqual(json.loads(output.getvalue())['code'],'DEVICE_REPORT_TOKEN_REQUIRED')

    def test_cli_explicit_token_free_serve_never_reads_token_and_closes_owned_server(self):
        class NoTokenEnvironment(dict):
            def get(self,key,default=None):
                if key=='FISHERY_DEVICE_REPORT_TOKEN':raise AssertionError('token must not be read')
                return super().get(key,default)
        with (patch('apps.device_reports.__main__.os.environ',NoTokenEnvironment()),
              patch('werkzeug.serving.make_server') as factory,
              patch('sys.stdout',new=io.StringIO()) as output):
            self.assertEqual(main(['--directory',str(self.root/'reports'),'--device-id',DEVICE,
                '--serve','--no-token','--bind','192.168.2.193']),0)
        factory.assert_called_once()
        self.assertEqual(factory.call_args.args[:2],('192.168.2.193',8780))
        factory.return_value.serve_forever.assert_called_once_with()
        factory.return_value.server_close.assert_called_once_with()
        status=json.loads(output.getvalue())
        self.assertEqual(status['code'],'DEVICE_REPORT_LISTENING')
        self.assertEqual(status['auth_mode'],'NONE_LAN')
        self.assertNotIn(TOKEN,output.getvalue())
        self.assertNotIn(report()['report_text'],output.getvalue())
        # Test client exercises the actual CLI-built app; make_server was mocked.
        response=factory.call_args.args[2].test_client().post('/api/fish/reports',data=raw(),content_type='application/json')
        self.assertEqual(response.json['status'],'accepted')

    def test_cli_token_free_check_opens_no_database_and_reads_no_token(self):
        class NoTokenEnvironment(dict):
            def get(self,key,default=None):
                if key=='FISHERY_DEVICE_REPORT_TOKEN':raise AssertionError('check must not read token')
                return super().get(key,default)
        with (patch('apps.device_reports.storage.sqlite3.connect',side_effect=AssertionError('check must not open DB')),
              patch('apps.device_reports.__main__.os.environ',NoTokenEnvironment()),
              patch('werkzeug.serving.make_server',side_effect=AssertionError('check must not listen')),
              patch('sys.stdout',new=io.StringIO()) as output):
            self.assertEqual(main(['--directory',str(self.root/'absent'),'--device-id',DEVICE,'--check','--no-token']),0)
        status=json.loads(output.getvalue())
        self.assertEqual(status['code'],'DEVICE_REPORT_CONFIG_CHECKED')
        self.assertEqual(status['auth_mode'],'NONE_LAN')
        self.assertFalse(status['database_opened'])
        self.assertFalse(status['credential_checked'])
        self.assertEqual(status['network_requests'],0)

    def test_concurrent_duplicates_commit_failure_and_no_reinitialization(self):
        def receive(_):return self.store.receive(raw(),device_id=DEVICE,now=NOW)['status']
        with ThreadPoolExecutor(max_workers=4) as executor:results=list(executor.map(receive,range(8)))
        self.assertEqual(results.count('accepted'),1);self.assertEqual(results.count('duplicate'),7)
        with self.assertRaisesRegex(ReportError,'STORE_EXISTS'):ReportStore.initialize(self.root/'reports')
        with patch.object(self.store,'receive',side_effect=ReportError('DEVICE_REPORT_STORAGE_UNAVAILABLE',503)):
            self.assertEqual(self.send().status_code,503)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            with patch('apps.device_reports.storage.sqlite3.connect',side_effect=sqlite3.OperationalError('synthetic')):
                self.assertEqual(self.send().status_code,503)
        for _ in range(65):response=self.send()
        self.assertEqual(response.status_code,429)

    def test_missing_corrupt_schema_and_offline_check_does_not_open_db_or_token(self):
        with self.assertRaisesRegex(ReportError,'STORE_MISSING'):ReportStore(self.root/'absent')
        damaged=self.root/'damaged';damaged.mkdir();(damaged/'device-reports.sqlite3').write_bytes(b'bad fixture')
        with self.assertRaises(ReportError):ReportStore(damaged)
        with closing(sqlite3.connect(self.store.path)) as db:db.execute('PRAGMA user_version=99')
        with self.assertRaisesRegex(ReportError,'SCHEMA_UNSUPPORTED'):ReportStore(self.root/'reports')
        with (patch('apps.device_reports.storage.sqlite3.connect',side_effect=AssertionError('no database')),
              patch('apps.device_reports.__main__.os.environ',{}),patch('sys.stdout',new=io.StringIO())):
            self.assertEqual(main(['--directory',str(self.root/'absent'),'--device-id',DEVICE,'--check']),0)
            self.assertEqual(main(['--directory',str(self.root),'--device-id',DEVICE,'--bind','0.0.0.0','--check']),1)

    def test_water_only_no_visual_generation_server_guard_and_no_false_recovery(self):
        service=MonitoringService(MonitoringRepository(self.root/'monitoring.sqlite3'),clock=lambda:NOW)
        sim=Simulator(start=NOW-timedelta(seconds=10),scenario='suspected_disease',mode='water-only')
        with patch.object(sim.visual_generator,'generate',side_effect=AssertionError('no visual generation')):batch=sim.advance()
        validate_batch(batch,now=NOW,device_ids={'sim-pond-1'})
        self.assertIsNone(batch['visual']);self.assertIsNotNone(batch['water'])
        client=create_app(data_service=service,ingestion_token=TOKEN,simulation_mode='water-only',
            device_report_store=ReportStore(self.root/'reports',read_only=True),device_report_device_id=DEVICE).test_client()
        headers={'X-Simulator-Token':TOKEN}
        full=Simulator(start=NOW-timedelta(seconds=10),scenario='suspected_disease').advance()
        self.assertEqual(client.post('/api/ingestion/batches',json=full,headers=headers).status_code,403)
        self.assertEqual(client.post('/api/ingestion/batches',json=batch,headers=headers).status_code,200)
        self.assertIsNone(service.repository.read('sim-pond-1','visual'))
        # Raw device report writes never enter Monitoring at all.
        before=self.root.joinpath('monitoring.sqlite3').read_bytes()
        self.send();self.assertEqual(self.root.joinpath('monitoring.sqlite3').read_bytes(),before)
        boot=client.get('/api/bootstrap').json
        self.assertEqual(boot['integration']['device_reports']['items'][0]['report']['device_id'],DEVICE)
        self.assertIsNone(boot['cameras'][0]['stream_url'])
        self.assertEqual(boot['monitoring']['source_kind'],'simulator')
        self.assertTrue(all(e.get('source_kind')!='device_report' for e in boot['events']))
        self.assertEqual(len(boot['integration']['device_reports']['items']),1)
        legacy=create_app(data_service=service,ingestion_token=TOKEN).test_client()
        self.assertNotIn('integration',legacy.get('/api/bootstrap').json)
        service.clock=lambda:NOW+timedelta(seconds=10)
        full=Simulator(start=NOW).advance()
        self.assertEqual(legacy.post('/api/ingestion/batches',json=full,headers=headers).status_code,200)
        with self.assertRaises(ValueError):Simulator(start=NOW,mode='unknown')
        web,simargs=commands('python','normal',8766,42,simulation_mode='water-only',device_report_directory=self.root/'reports',device_report_device_id=DEVICE)
        self.assertIn('--simulation-mode',web);self.assertIn('--mode',simargs)

    def test_partial_batches_interrupt_old_visual_evidence_without_resolving_or_deleting(self):
        now=NOW
        service=MonitoringService(MonitoringRepository(self.root/'monitoring.sqlite3'),clock=lambda:now)
        sim=Simulator(start=NOW-timedelta(seconds=10))
        first=sim.advance();first['visual']['anomaly_counts']['suspected_lesion']=1
        service.ingest(first)
        old=[e for e in service.repository.events() if e['code']=='SUSPECTED_LESION'][0]
        for _ in range(4):
            now+=timedelta(seconds=10)
            batch=sim.advance();batch['visual']=None;service.ingest(batch)
        kept=[e for e in service.repository.events() if e['id']==old['id']][0]
        self.assertNotEqual(kept['lifecycle_state'],'RESOLVED')
        self.assertIsNone(kept.get('resolved_at'))
        self.assertEqual(service.repository.read('sim-pond-1','visual')['batch_id'],first['batch_id'])

    def test_actual_insert_failure_returns_retryable_error_without_false_acceptance(self):
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER simulated_disk_failure BEFORE INSERT ON reports BEGIN SELECT RAISE(ABORT,'synthetic'); END")
            db.commit()
        self.assertEqual(self.send().status_code,503)
        self.assertEqual(self.store.recent(DEVICE,now=NOW)['items'],[])
        with self.store.connection() as db:db.execute('DROP TRIGGER simulated_disk_failure');db.commit()
        self.assertEqual(self.send().json['status'],'accepted')

    def test_corrupt_or_removed_store_does_not_recreate_or_fallback(self):
        self.store.path.unlink() # Only this test's disposable store.
        self.assertEqual(self.send().status_code,503)
        self.assertFalse(self.store.path.exists())

    def test_water_only_empty_channel_sends_no_false_normal_window(self):
        sim=Simulator(start=NOW,mode='water-only')
        from apps.simulator.scenarios import SCENARIOS
        with patch('apps.simulator.generator.at_time',return_value={'online':True,'water_online':False,'visual_online':True}):
            self.assertIsNone(sim.advance())


if __name__=='__main__':unittest.main()
