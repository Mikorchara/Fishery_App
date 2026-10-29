"""Owned loopback Web/Simulator and independent RO Bot; synthetic instance only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from urllib.request import urlopen

from apps.management_web.tests import test_windows_demo_lifecycle as demo
from apps.ai_backend.sdk_resources import SDK_RESOURCES

ROOT = Path(__file__).resolve().parents[3]

# Child keeps an actual query_only SQLite connection open while querying through
# the public Monitoring facade. It never holds a read transaction across sleeps.
PROBE = '''
import json,os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from apps.qq_bot.monitoring_source import InstanceMonitoring,MonitoringSourceConfig
from apps.ai_backend.sdk_resources import SDK_RESOURCES
from apps.ai_backend.model_gateway import GatewayError
source=InstanceMonitoring(MonitoringSourceConfig('m2-cross-process',Path(sys.argv[2]),('sim-pond-1',)))
with source._service.repository.connection() as db:
    assert db.execute('PRAGMA query_only').fetchone()[0]==1
    try: db.execute('DELETE FROM events');raise AssertionError('write allowed')
    except __import__('sqlite3').DatabaseError: pass
    capture=source.capture_water('sim-pond-1')
    assert capture.analysis.device_id=='sim-pond-1'
    # Process-local SDK fuse must not poison Web or this test's SDK budget.
    lease=SDK_RESOURCES.reserve();lease.fail('SDK_CLEANUP_FAILED');lease.settle()
    try:SDK_RESOURCES.reserve();raise AssertionError('quarantine lost')
    except GatewayError:pass
    Path(sys.argv[3]).write_text(json.dumps({'pid':os.getpid(),'read':True,'query_only':True,'quarantined':True}))
    if sys.argv[4]=='normal':time.sleep(.3)
    else:
        while True:time.sleep(.1)
'''


@unittest.skipUnless(os.name == 'nt', 'Windows process isolation')
class ProcessIsolationTests(unittest.TestCase):
    setUp = demo.WindowsDemoLifecycleTests.setUp
    start = demo.WindowsDemoLifecycleTests.start
    wait_until = demo.WindowsDemoLifecycleTests.wait_until
    batches = demo.WindowsDemoLifecycleTests.batches
    kill_owned = staticmethod(demo.WindowsDemoLifecycleTests.kill_owned)

    def test_bot_read_stop_and_crash_do_not_stop_web_simulator_or_event_ingestion(self):
        supervisor, supervisor_pid = self.start()
        self.wait_until(lambda: len(self.batches()) >= 1, timeout=18)
        parent_budget = SDK_RESOURCES.snapshot()
        for mode in ('normal', 'crash'):
            with self.subTest(mode=mode):
                checkpoint = self.root/('bot-'+mode+'.json')
                log = (self.root/('bot-'+mode+'.log')).open('wb')
                self.addCleanup(log.close)
                bot = subprocess.Popen([sys.executable, '-I', '-B', '-c', PROBE, str(ROOT),
                    str(self.paths.data_root), str(checkpoint), mode], cwd=ROOT,
                    stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                def stop_owned(child=bot):
                    if child.poll() is None: child.terminate()
                    child.wait(timeout=8)
                self.addCleanup(stop_owned)
                self.wait_until(lambda: checkpoint.exists() or bot.poll() is not None)
                self.assertTrue(checkpoint.exists(), (self.root/('bot-'+mode+'.log')).read_text(errors='replace'))
                report = json.loads(checkpoint.read_text())
                self.assertTrue(report['read'] and report['query_only'] and report['quarantined'])
                count = len(self.batches())
                if mode == 'crash':
                    # Terminate the executing Python PID we own, including the
                    # venv wrapper, never a discovered/unrelated process.
                    self.kill_owned(report['pid'])
                bot.wait(timeout=8)
                self.assertIsNone(supervisor.poll())
                self.wait_until(lambda: len(self.batches()) > count, timeout=15)
                with urlopen(f'http://127.0.0.1:{self.port}/api/bootstrap', timeout=2) as response:
                    self.assertEqual(response.status, 200)
                with urlopen(f'http://127.0.0.1:{self.port}/api/events', timeout=2) as response:
                    self.assertIsInstance(json.load(response), dict)
                self.assertTrue(demo.alive(supervisor_pid))
        self.assertEqual(SDK_RESOURCES.snapshot(), parent_budget)
