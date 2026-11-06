"""Owned status files survive brief Windows reader/replace contention."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from apps.qq_bot.management_config import ROOT
from scripts.dev import stack_console


@unittest.skipUnless(os.name=='nt','Windows status replacement sharing')
class StackStatusTests(unittest.TestCase):
    def setUp(self):
        temporary=TemporaryDirectory(dir=ROOT/'outputs/test-tmp')
        self.addCleanup(temporary.cleanup)
        self.directory=Path(temporary.name)
        (self.directory/'stack.json').write_text(json.dumps({'nonce':'synthetic-status'}),encoding='utf8')
        self.write('STARTING')
        self.target=self.directory/'web.status.json'

    def write(self,state):
        stack_console.write_status(self.directory,'web',state=state,code='SERVICE_'+state,exit_code=None)

    def test_real_reader_released_after_failed_replace_allows_same_write_to_finish(self):
        blocked=threading.Event()
        original=os.replace
        failures=[]
        observed=[]

        def replace(source,target):
            try:
                return original(source,target)
            except OSError as error:
                observed.append(getattr(error,'winerror',None))
                blocked.set()
                raise

        def writer():
            try:
                self.write('RUNNING')
            except BaseException as error:
                failures.append(error)

        # Exercise an actual Windows read handle, not a mocked PermissionError.
        with self.target.open('r',encoding='utf8') as reader, patch.object(stack_console.os,'replace',replace):
            reader.read()
            thread=threading.Thread(target=writer,name='synthetic-status-writer')
            thread.start()
            self.assertTrue(blocked.wait(2),'reader did not block an actual replace')
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures,[])
        self.assertTrue(observed)
        self.assertTrue(set(observed)<={5,32,33})
        self.assertEqual(json.loads(self.target.read_text(encoding='utf8'))['state'],'RUNNING')
        self.assertEqual(list(self.directory.glob('.web-*.tmp')),[])

    def test_persistent_real_reader_fails_boundedly_and_preserves_old_status(self):
        start=time.monotonic()
        with self.target.open('r',encoding='utf8') as reader:
            reader.read()
            with self.assertRaises(PermissionError) as raised:
                self.write('RUNNING')
        self.assertIn(raised.exception.winerror,(5,32,33))
        self.assertGreaterEqual(time.monotonic()-start,.45)
        self.assertLess(time.monotonic()-start,5)
        self.assertEqual(json.loads(self.target.read_text(encoding='utf8'))['state'],'STARTING')
        pending=list(self.directory.glob('.web-*.tmp'))
        self.assertEqual(len(pending),1)
        self.assertEqual(json.loads(pending[0].read_text(encoding='utf8'))['state'],'RUNNING')

    def test_other_replace_errors_and_fsync_failure_are_not_retried(self):
        with patch.object(stack_console.os,'replace',side_effect=OSError('synthetic storage failure')) as replace:
            with self.assertRaises(OSError):
                self.write('RUNNING')
        self.assertEqual(replace.call_count,1)
        with patch.object(stack_console.os,'fsync',side_effect=OSError('synthetic fsync failure')) as fsync:
            with patch.object(stack_console.os,'replace') as replace:
                with self.assertRaises(OSError):
                    self.write('RUNNING')
        self.assertEqual(fsync.call_count,1)
        replace.assert_not_called()
