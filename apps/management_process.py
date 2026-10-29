"""Cooperative Web lifetime ownership, only for new M3 marked isolated instances.

No QQ, AI, SQLite, process discovery or credential reads. Existing instances have
no marker and keep their original startup contract.
"""
from contextlib import contextmanager
import json
from pathlib import Path
from apps.ai_backend.secure_files import exclusive_lock, guard_path, FileBusyError

ISOLATED_MARKER_CONTRACT='management-isolated-simulator@1'

class InstanceWriterBusy(RuntimeError):
    code='MANAGEMENT_INSTANCE_WRITER_ALREADY_RUNNING'
    def __init__(self):super().__init__(self.code)

def marked_instance(root):
    if root is None:return False
    root=Path(root).resolve();marker=root/'qq-isolated-instance.json'
    if not marker.exists():return False
    guard_path(marker,regular=True)
    with marker.open('rb') as stream:raw=stream.read(4097)
    if len(raw)>4096:raise RuntimeError('ISOLATED_INSTANCE_MARKER_INVALID')
    value=json.loads(raw)
    if value.get('contract')!=ISOLATED_MARKER_CONTRACT or value.get('root')!=str(root):
        raise RuntimeError('ISOLATED_INSTANCE_MARKER_INVALID')
    return True

@contextmanager
def marked_instance_writer(root):
    if not marked_instance(root):yield;return
    try:
        with exclusive_lock(Path(root)/'.management-writer.lock'):yield
    except FileBusyError:raise InstanceWriterBusy() from None

def probe_writer(root):
    if not marked_instance(root):raise RuntimeError('STACK_NEW_ISOLATED_INSTANCE_REQUIRED')
    # Check does not create a lock file or change the instance.
    if (Path(root)/'.management-writer.lock').exists():
        with marked_instance_writer(root):pass
