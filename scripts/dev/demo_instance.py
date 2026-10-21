"""Explicit demo bootstrap: one read-only knowledge snapshot, no other user data."""
from contextlib import closing, contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from apps.management_paths import ManagementPaths
from apps.management_web.instance import safe_path, validate_instance, check_database


def knowledge_facts(path):
    """Compare every column/row (including IDs, versions and metadata), not DB bytes."""
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True)) as db:
        quote = lambda name: '"'+name.replace('"', '""')+'"'
        schema = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall()
        tables = {}
        for (table,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall():
            rows = db.execute('SELECT * FROM '+quote(table)).fetchall()
            encoded = sorted(json.dumps(row, ensure_ascii=False, separators=(',', ':'),
                default=lambda value: {'blob':value.hex()}) for row in rows)
            tables[table] = (len(rows), hashlib.sha256(json.dumps(encoded).encode()).hexdigest())
        return {'schema':schema, 'version':db.execute('PRAGMA user_version').fetchone()[0], 'tables':tables}


@contextmanager
def frozen_knowledge(path):
    """Deny write/delete handles; refuse active SQLite sidecars rather than alter them."""
    from apps.ai_backend import secure_files
    if os.name != 'nt':
        raise RuntimeError('DEMO_WINDOWS_REQUIRED')
    safe_path(path)
    if not path.is_file():
        raise RuntimeError('DEMO_SOURCE_KNOWLEDGE_MISSING')
    handle = secure_files._create_file(str(path), 0x80000000, 1, None, 3, 0x200080, None)
    if handle == ctypes.c_void_p(-1).value:
        raise RuntimeError('DEMO_SOURCE_BUSY_CLOSE_FORMAL_WEB')
    try:
        if any(Path(str(path)+suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
            raise RuntimeError('DEMO_SOURCE_BUSY_CLOSE_FORMAL_WEB')
        # A WAL-mode header without sidecars is also refused: a normal ro SQLite
        # open could create -shm/-wal. Never create these in the formal instance.
        with path.open('rb') as stream:
            header = stream.read(100)
        if header[:16] != b'SQLite format 3\0' or header[18:20] != b'\x01\x01':
            raise RuntimeError('DEMO_SOURCE_NOT_COLD_SQLITE')
        before = hashlib.sha256(path.read_bytes()).digest()
        yield
        if hashlib.sha256(path.read_bytes()).digest() != before:
            raise RuntimeError('DEMO_SOURCE_CHANGED')
    finally:
        secure_files._close(handle)


def demo_policy(directory):
    """Fresh demo-only user authorization via the existing policy writer."""
    from apps.ai_service.business_tools.registry import HISTORY_CANDIDATE_TOOL_NAMES
    from apps.ai_service.management_policy import ManagementToolPolicyStore
    from apps.ai_service.runtime.policy import UserToolPolicyStore
    from apps.ai_backend.tools import ToolRegistry
    inherited = UserToolPolicyStore(directory, ToolRegistry([]))
    store = ManagementToolPolicyStore(directory, inherited)
    store.save(HISTORY_CANDIDATE_TOOL_NAMES, expected_revision=store.snapshot().revision)


def prepare_demo(root, *, source=None):
    root = Path(root).absolute()
    target = root/'outputs'/'demo-instance'
    safe_path(target)
    paths = ManagementPaths.resolve(root, data_root=target)
    if target.exists():
        validate_instance(paths)
        # Reuse never opens the formal source or changes Policy/Settings/Knowledge.
        with closing(sqlite3.connect(paths.knowledge.as_uri()+'?mode=ro', uri=True)) as db:
            count = db.execute('SELECT count(*) FROM knowledge_records').fetchone()[0]
        if count == 0:
            raise RuntimeError('DEMO_KNOWLEDGE_EMPTY_REQUIRES_REVIEW')
        return paths, False, count
    if source is None:
        source = ManagementPaths.resolve(root, user_data=True).knowledge
    source = Path(source).absolute()
    from apps.knowledge.migration import backup
    from apps.monitoring.repository import MonitoringRepository
    stage = None
    try:
        with frozen_knowledge(source):
            check_database(source, 'KNOWLEDGE')
            facts = knowledge_facts(source)
            count = facts['tables']['knowledge_records'][0]
            if count == 0:
                raise RuntimeError('DEMO_SOURCE_KNOWLEDGE_EMPTY')
            target.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix='.demo-init-', dir=target.parent))
            candidate = ManagementPaths.resolve(root, data_root=stage)
            MonitoringRepository(candidate.monitoring)
            backup(source, candidate.knowledge)
            if knowledge_facts(candidate.knowledge) != facts:
                raise RuntimeError('DEMO_KNOWLEDGE_COPY_MISMATCH')
            candidate.traces.parent.mkdir()
            demo_policy(candidate.policy_directory)
            validate_instance(candidate)
        safe_path(target)
        # Windows rename refuses even an existing empty directory. No replace,
        # merge, repair, or retry against an instance edited by someone else.
        os.rename(stage, target)
        stage = None
        return paths, True, count
    finally:
        if stage is not None:
            # Only synthetic files in our unique, verified project-local stage.
            if stage.parent.resolve() != target.parent.resolve() or not stage.name.startswith('.demo-init-'):
                raise RuntimeError('DEMO_UNSAFE_STAGE')
            safe_path(stage)
            shutil.rmtree(stage)
