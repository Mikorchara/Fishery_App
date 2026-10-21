"""Real Windows consoles/process trees and ten-second data, isolated data only."""
import ctypes
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from urllib.request import urlopen

from apps.management_paths import ManagementPaths
from apps.management_web.instance import initialize_instance
from scripts.dev.local_session import ROOT, require_free_port


def descendants(parent):
    """Read PIDs only, never inspect process environments/credentials."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    class Process(ctypes.Structure):
        _fields_ = [('size', wt.DWORD), ('usage', wt.DWORD), ('pid', wt.DWORD),
                    ('heap', ctypes.c_size_t), ('module', wt.DWORD), ('threads', wt.DWORD),
                    ('parent', wt.DWORD), ('priority', wt.LONG), ('flags', wt.DWORD), ('name', wt.WCHAR*260)]
    kernel.CreateToolhelp32Snapshot.restype = wt.HANDLE
    kernel.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(Process)]
    kernel.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(Process)]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError('process snapshot unavailable')
    pairs = []
    try:
        entry = Process(); entry.size = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while found:
            pairs.append((entry.pid, entry.parent))
            found = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    result = {parent}
    for _ in range(len(pairs)):
        more = {pid for pid, owner in pairs if owner in result}
        if more <= result:
            break
        result |= more
    return result-{parent}


def alive(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel.OpenProcess.restype = wt.HANDLE
    kernel.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    kernel.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        return False
    try:
        return kernel.WaitForSingleObject(handle, 0) == 0x102
    finally:
        kernel.CloseHandle(handle)


@unittest.skipUnless(os.name == 'nt', 'Windows consoles/job objects')
class WindowsDemoLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        paths = ManagementPaths.resolve(ROOT, data_root=self.root/'instance')
        initialize_instance(paths)
        self.paths = paths
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0)); self.port = reserve.getsockname()[1]

    def wait_until(self, condition, timeout=15):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.1)
        self.fail('owned session condition timed out')

    def start(self):
        pid_file = self.root/'supervisor.pid'
        pid_file.unlink(missing_ok=True)
        # Record the executing Python PID (the venv bootstrap has another PID).
        code = ('import os,sys,runpy;from pathlib import Path;'
                'Path(sys.argv.pop(1)).write_text(str(os.getpid()));'
                'script=sys.argv.pop(1);sys.argv[0]=script;'
                'runpy.run_path(script,run_name="__main__")')
        output = (self.root/'session.log').open('wb'); self.addCleanup(output.close)
        child = subprocess.Popen([sys.executable, '-I', '-B', '-u', '-c', code, str(pid_file),
            str(ROOT/'scripts/dev/local_session.py'), '--show-terminals', '--no-assistant',
            '--port', str(self.port), '--data-root', str(self.paths.data_root)],
            cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        # No external process is ever killed: this is the PID we just created.
        def cleanup():
            if child.poll() is None:
                if pid_file.exists():
                    self.kill_owned(int(pid_file.read_text()))
                child.terminate()
            child.wait(timeout=8)
        self.addCleanup(cleanup)
        from scripts.dev.local_session import ready
        self.wait_until(lambda: child.poll() is not None or ready(self.port))
        self.assertIsNone(child.poll(), (self.root/'session.log').read_text(errors='replace'))
        self.wait_until(lambda: len(descendants(int(pid_file.read_text()))) >= 4)
        return child, int(pid_file.read_text())

    @staticmethod
    def kill_owned(pid):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]; kernel.OpenProcess.restype = wt.HANDLE
        kernel.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]; kernel.CloseHandle.argtypes = [wt.HANDLE]
        handle = kernel.OpenProcess(1, False, pid)
        if handle:
            try: kernel.TerminateProcess(handle, 1)
            finally: kernel.CloseHandle(handle)

    def close_console(self, role):
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]; user.FindWindowW.restype = wt.HWND
        user.PostMessageW.argtypes = [wt.HWND, wt.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        title = 'AI 监测系统 · '+role+' · '+str(self.port)
        window = user.FindWindowW(None, title)
        self.assertTrue(window, 'visible console missing: '+title)
        self.assertTrue(user.PostMessageW(window, 0x10, 0, 0))  # WM_CLOSE, own unique title.

    def test_two_consoles_continuous_reports_close_either_restart_and_port_conflict(self):
        for index, role in enumerate(('Simulator', 'Web')):
            with self.subTest(close=role):
                child, pid = self.start(); owned = descendants(pid)|{pid}
                if index == 0:
                    def two_reports():
                        with urlopen(f'http://127.0.0.1:{self.port}/api/monitoring', timeout=1) as response:
                            return json.load(response)
                    time.sleep(10.5)
                    first = two_reports()
                    time.sleep(10)
                    second = two_reports()
                    self.assertNotEqual(first, second)
                    self.assertIn('window_mean', json.dumps(second))
                    self.assertIn('simulator', json.dumps(second))
                    duplicate = subprocess.run([sys.executable, '-I', '-B', str(ROOT/'scripts/dev/local_session.py'),
                        '--port', str(self.port), '--show-terminals', '--data-root', str(self.paths.data_root)],
                        cwd=ROOT, capture_output=True, timeout=8)
                    self.assertEqual(duplicate.returncode, 1)
                    self.assertIn(b'LOCAL_PORT_IN_USE', duplicate.stderr)
                    self.assertIsNone(child.poll())
                self.close_console(role)
                child.wait(timeout=12)
                self.assertEqual(child.returncode, 0, (self.root/'session.log').read_text(errors='replace'))
                self.wait_until(lambda: not any(alive(p) for p in owned))
                self.wait_until(lambda: self.port_free())

    def port_free(self):
        try: require_free_port(self.port); return True
        except RuntimeError: return False

    def test_forced_supervisor_exit_reaps_all_descendants(self):
        child, pid = self.start(); owned = descendants(pid)
        self.kill_owned(pid)
        child.wait(timeout=8)
        self.wait_until(lambda: not any(alive(p) for p in owned))
        self.wait_until(lambda: self.port_free())
