"""MIG-4B: five fixed sources, dry-run by default, Windows no-replace publication.

No credential access, network calls, source writes, initialization or cleanup.
Run with this project's Python -I -B; see apps/docs/deep-dive/OPERATIONS.md.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager, ExitStack
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from apps.management_paths import ManagementPaths
from apps.management_web.instance import safe_path, validate_instance, check_database
from apps.ai_backend import secure_files
from apps.ai_service.management_policy import ManagementToolPolicyStore
from apps.ai_service.runtime.policy import UserToolPolicyStore
from apps.ai_backend.tools.registry import ToolRegistry
from apps.ai_service.settings_store import PreferencesStore
from apps.ai_service.settings import ManagementSettingsService

SOURCE = Path(r'D:\CodexProject\Fishery_AI_Prototype')
APPROVED_HEAD = '6e67202ba1cafae87bac0375e63a6a177789f38e'
BASELINE = {
    'monitoring': '35e01cb060a838411bfbaeaf54a618ded6f5b4e75878d2044bcf5ba29cf5ea3d',
    'knowledge': '23e85fa9869abdc981d68f576bd2f9ec014929a9f90f1d3f13a873f35168fc80',
    'settings': '29dfa2abfc9cf9bd3f982563aa73839209e0fc60c1f9ef1429173a5d066623ef',
    'management_policy': '851554223af91535a23cbe30c9faeb76f886f9adbc17e0646d1931b35310b10a',
    'shared_policy': '2deeb81c19bd7adc0428e08f7e290d87fcf28672a054fc041ecbedd5131103a2',
}
TOOLS = ('get_current_water_quality', 'search_fishery_knowledge', 'get_water_quality_history')


class MigrationError(Exception):
    """Codes only: never print database records, submitted values or raw exceptions."""


def require(condition, code):
    if not condition:
        raise MigrationError(code)


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def files(paths):
    return dict(monitoring=paths.monitoring, knowledge=paths.knowledge, settings=paths.settings,
                management_policy=paths.policy_directory/'management_assistant_policy.json',
                shared_policy=paths.policy_directory/'tool_policies.json')


def file_facts(paths):
    return {name: {'bytes': path.stat().st_size, 'sha256': sha(path)} for name, path in files(paths).items()}


def validate_existing(paths):
    if paths.data_root is None:
        # Legacy source locations are explicit inputs, never an initialized instance.
        check_database(paths.monitoring, 'MONITORING')
        check_database(paths.knowledge, 'KNOWLEDGE')
    else:
        validate_instance(paths)


def cold_database(path):
    safe_path(path)
    require(path.is_file(), 'SOURCE_FILE_MISSING')
    require(not any(os.path.lexists(str(path)+ext) for ext in ('-wal', '-shm', '-journal')),
            'SQLITE_SIDECAR_PRESENT_STOP_FOR_REVIEW')
    with path.open('rb') as stream:
        header = stream.read(100)
    require(header[:16] == b'SQLite format 3\0' and header[18:20] == b'\1\1',
            'SQLITE_NOT_COLD_ROLLBACK_DATABASE')


@contextmanager
def readonly_db(path):
    cold_database(path)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        yield db


@contextmanager
def freeze_files(paths):
    """GENERIC_READ + FILE_SHARE_READ denies existing/future WRITE and DELETE handles.

    Handles are held for the entire five-file snapshot and publication. No byte
    range lock, writable SQLite connection or persistent source lock file is used.
    """
    require(os.name == 'nt', 'WINDOWS_REQUIRED')
    with ExitStack() as stack:
        for path in files(paths).values():
            safe_path(path)
            require(path.is_file(), 'SOURCE_FILE_MISSING')
            secure_files.check_volume(path)
            handle = secure_files._create_file(str(path), 0x80000000, 1, None, 3, 0x200080, None)
            require(handle != ctypes.c_void_p(-1).value, 'FILE_BUSY_OR_UNREADABLE_STOP_FOR_REVIEW')
            stack.callback(secure_files._close, handle)
        yield


def database_facts(path):
    quote = lambda name: '"'+name.replace('"', '""')+'"'
    with readonly_db(path) as db:
        db.execute('BEGIN')
        require([row[0] for row in db.execute('PRAGMA integrity_check')] == ['ok'], 'DATABASE_INTEGRITY_FAILED')
        schema = [list(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name')]
        result = {'schema': schema, 'schema_sha256': hashlib.sha256(encode(schema)).hexdigest(),
                  'user_version': db.execute('PRAGMA user_version').fetchone()[0],
                  'schema_version': db.execute('PRAGMA schema_version').fetchone()[0],
                  'application_id': db.execute('PRAGMA application_id').fetchone()[0], 'integrity': 'ok', 'tables': {}}
        for (table,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall():
            columns = [row[1] for row in db.execute('PRAGMA table_info('+quote(table)+')')]
            # All columns give deterministic order even for tables without a PK.
            projection = ','.join(map(quote, columns))
            digest, count = hashlib.sha256(), 0
            for row in db.execute('SELECT '+projection+' FROM '+quote(table)+' ORDER BY '+projection):
                values = [{'sqlite_blob_hex': v.hex()} if isinstance(v, bytes) else v for v in row]
                raw = encode(values)
                digest.update(len(raw).to_bytes(8, 'big')); digest.update(raw); count += 1
            result['tables'][table] = {'columns': columns, 'count': count, 'rows_sha256': digest.hexdigest()}
        if 'knowledge_records' in result['tables']:
            result['knowledge_revision'] = [list(r) for r in db.execute('SELECT id,revision FROM knowledge_revision ORDER BY id')]
            result['migration_version'] = db.execute("SELECT value FROM knowledge_metadata WHERE key='migration_version'").fetchone()[0]
            result['origin_status_counts'] = [list(r) for r in db.execute('SELECT origin,status,count(*) FROM knowledge_records GROUP BY origin,status ORDER BY origin,status')]
        db.rollback()
        return result


def configuration_facts(paths):
    """Use real selection/budget resolvers with no repository, credential or I/O."""
    from apps.ai_service.service import ManagementAssistantService
    from apps.ai_service.execution import load_execution_config
    from apps.ai_service.streaming import load_streaming_config
    from apps.ai_service.history_execution import load_history_config
    from apps.ai_service.normal_selection import load_unified_tool_trials
    from apps.monitoring.service import MonitoringService
    from apps.knowledge.service import KnowledgeContentService
    def forbidden(*args, **kwargs):
        raise MigrationError('NETWORK_OR_TRACE_FORBIDDEN')
    class NoIO:
        def __getattr__(self, name):
            return forbidden
    store = PreferencesStore(paths.settings)
    preferences = ManagementSettingsService.validate(store.document()['preferences'])
    monitoring = MonitoringService(None)
    require(preferences['device_id'] in {d['id'] for d in monitoring.devices()}, 'SAVED_DEVICE_NOT_REGISTERED')
    backend = ManagementAssistantService(monitoring, credentials=NoIO(), traces=NoIO(),
        policy_directory=paths.policy_directory, gateway_factory=forbidden, knowledge=KnowledgeContentService(None),
        execution_config=load_execution_config(enable_trial=True), streaming_config=load_streaming_config(enable_trial=True),
        history_config=load_history_config(enable_trial=True), unified_config=load_unified_tool_trials(normal=True, streaming=True))
    backend.settings_store = store
    bootstrap = backend.bootstrap(preferences['device_id'])
    model = next(p for p in bootstrap['presets'] if p['preset_id'] == preferences['preset_id'])
    return {name: {key: model[field][key] for key in ('can_send', 'max_output_tokens', 'tools', 'max_tool_calls', 'max_tool_rounds')}
            for name, field in (('normal', 'execution'), ('streaming', 'streaming'))}


def application_readonly_check(paths):
    """Existing-instance validation plus in-memory Flask GETs; no server or model."""
    from apps.monitoring.repository import MonitoringRepository
    from apps.monitoring.service import MonitoringService
    from apps.knowledge.repository import KnowledgeRepository
    from apps.knowledge.service import KnowledgeContentService
    from apps.management_web.app import create_app
    class ReadOnlyMonitoring(MonitoringRepository):
        @contextmanager
        def connection(self):
            with readonly_db(self.path) as db:
                yield db
    class ReadOnlyKnowledge(KnowledgeRepository):
        @contextmanager
        def connection(self, *, write=False):
            require(not write, 'APPLICATION_WRITE_FORBIDDEN')
            with readonly_db(self.path) as db:
                yield db
    validate_existing(paths)
    monitoring = MonitoringService(ReadOnlyMonitoring(paths.monitoring, require_existing=True))
    knowledge = KnowledgeContentService(ReadOnlyKnowledge(paths.knowledge, require_existing=True))
    app = create_app(data_service=monitoring, knowledge_service=knowledge)
    with app.test_client() as client:
        bootstrap = client.get('/api/bootstrap', base_url='http://localhost')
        entries = client.get('/api/knowledge', base_url='http://localhost')
        require(bootstrap.status_code == entries.status_code == 200, 'APPLICATION_READONLY_GET_FAILED')
        result = {'bootstrap_http': 200, 'knowledge_http': 200, 'knowledge_count': entries.get_json()['total'],
                  'data_mode': bootstrap.get_json()['data_mode'], 'repositories': [str(paths.monitoring), str(paths.knowledge)],
                  'provider_requests': 0, 'simulator_started': False}
    return result


def snapshot(paths):
    before = file_facts(paths)
    for path in (paths.monitoring, paths.knowledge):
        cold_database(path)
    validate_existing(paths)
    document = PreferencesStore(paths.settings).document()
    preferences = ManagementSettingsService.validate(document['preferences'])
    # All JSON readers enforce existing bounded, duplicate-key-rejecting schemas.
    inherited = UserToolPolicyStore(paths.policy_directory, ToolRegistry([]))
    policy = ManagementToolPolicyStore(paths.policy_directory, inherited)
    policy_public = policy.public()
    require(policy_public['source'] == 'MANAGEMENT_OVERRIDE' and tuple(policy_public['selected_tools']) == TOOLS,
            'EFFECTIVE_THREE_TOOL_AUTHORIZATION_REQUIRED')
    safe_preferences = {k: v for k, v in preferences.items() if k != 'device_id'}
    safe_preferences['device_id_sha256'] = hashlib.sha256(preferences['device_id'].encode()).hexdigest()
    with paths.settings.open('rb') as stream:
        settings_schema = json.load(stream)['schema_version']
    result = {'databases': {name: database_facts(path) for name, path in
                           (('monitoring', paths.monitoring), ('knowledge', paths.knowledge))},
              'settings': {'schema_version': settings_schema, 'preferences': safe_preferences,
                           'output_budgets': document['output_budgets'], 'budget_revision': document['budget_revision']},
              'management_policy': policy_public, 'shared_policy': inherited.load(),
              'local_trial_configuration': configuration_facts(paths)}
    smoke = application_readonly_check(paths)
    require(before == file_facts(paths), 'FILES_CHANGED_DURING_READ')
    return {'files': before, 'semantic': result, 'application': smoke}


def require_equal(actual, expected):
    def logical(value):
        value = json.loads(encode(value['semantic']))
        for database in value['databases'].values():
            # Backup API assigns a destination schema cookie. SQL definitions,
            # user_version, every row and all other application facts must match.
            database.pop('schema_version')
        return value
    require(logical(actual) == logical(expected), 'LOGICAL_DATA_OR_SCHEMA_MISMATCH')
    for name in ('settings', 'management_policy', 'shared_policy'):
        require(actual['files'][name] == expected['files'][name], 'JSON_BYTES_MISMATCH')
    require(actual['application']['knowledge_count'] == expected['application']['knowledge_count'], 'KNOWLEDGE_COUNT_MISMATCH')


def inspect_processes(unrelated_pids):
    # Never serialize command lines: they might contain credentials from other apps.
    command = r"""
        $all = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        $skip = [Collections.Generic.HashSet[int]]::new()
        $p = [int]PARENT_PID
        while ($p -gt 0 -and $skip.Add($p)) {
            $row = $all | Where-Object { $_.ProcessId -eq $p } | Select-Object -First 1
            if (-not $row) { break }; $p = [int]$row.ParentProcessId
        }
        $rows = @($all | Where-Object {
            -not $skip.Contains([int]$_.ProcessId) -and (
              $_.Name -match '^(python(w)?([0-9.]*)?|sqlite3|DB Browser for SQLite|DBeaver|uvicorn|gunicorn)\.exe$' -or
              ($_.Name -match '^(node|uv)\.exe$' -and $_.CommandLine -match 'management_web|apps\.simulator|local_session')
            )
        } | ForEach-Object {
            [pscustomobject]@{pid=$_.ProcessId;name=$_.Name;fishery_reference=([string]$_.CommandLine -match
              'Fishery_Management|Fishery_AI_Prototype|management_web|apps\.simulator|local_session|monitoring\.sqlite3|knowledge\.sqlite3')}
        })
        [pscustomobject]@{processes=$rows;localappdata=[Environment]::GetFolderPath('LocalApplicationData')} | ConvertTo-Json -Depth 4 -Compress
    """.replace('PARENT_PID', str(os.getpid()))
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, timeout=25, check=False)
    require(result.returncode == 0, 'PROCESS_INSPECTION_FAILED')
    value = json.loads(result.stdout.decode('utf-8-sig'))
    blocked = [p for p in value['processes'] if p['fishery_reference'] or p['pid'] not in unrelated_pids]
    require(not blocked, 'UNCONFIRMED_WRITER_PIDS:'+','.join(str(p['pid']) for p in blocked))
    return value['localappdata']


def parent_check(parent):
    safe_path(parent)
    secure_files.guard_path(parent)
    secure_files.check_volume(parent)
    secure_files.inspect_policy(parent, directory=True, user_owned=True)


def new_directory(path):
    safe_path(path)
    require(not os.path.lexists(path), 'NEW_DIRECTORY_ALREADY_EXISTS')
    secure_files.private_directory(path)
    secure_files.inspect_policy(path, directory=True, user_owned=True)


def write_new(path, raw):
    safe_path(path)
    require(not os.path.lexists(path), 'OUTPUT_FILE_ALREADY_EXISTS')
    secure_files.write_private(path, raw)


def populate(source, destination):
    new_directory(destination.data_root)
    new_directory(destination.policy_directory)
    new_directory(destination.traces.parent)
    for name, target in files(destination).items():
        origin = files(source)[name]
        if name in ('monitoring', 'knowledge'):
            write_new(target, b'')
            with readonly_db(origin) as db, closing(sqlite3.connect(target.as_uri()+'?mode=rw', uri=True)) as output:
                db.backup(output)
        else:
            write_new(target, origin.read_bytes())
        secure_files.inspect_policy(target)


def publish(stage, target):
    require(os.name == 'nt', 'WINDOWS_REQUIRED')
    safe_path(stage); safe_path(target)
    require(stage.parent == target.parent and stage.stat().st_dev == target.parent.stat().st_dev, 'PUBLICATION_VOLUME_MISMATCH')
    require(not os.path.lexists(target), 'TARGET_ALREADY_EXISTS')
    # Windows rename refuses ALL existing destinations, including empty dirs.
    # No os.replace, REPLACE_EXISTING, COPY_ALLOWED, fallback or cleanup.
    os.rename(stage, target)


def execute(plan, source, target, check_writers):
    parent_check(target.data_root.parent)
    require(not os.path.lexists(target.data_root), 'TARGET_ALREADY_EXISTS')
    backup = ManagementPaths.resolve(ROOT, data_root=Path(plan['backup']))
    stage = ManagementPaths.resolve(ROOT, data_root=Path(plan['stage']))
    require(not os.path.lexists(backup.data_root) and not os.path.lexists(stage.data_root), 'OPERATION_PATH_ALREADY_EXISTS')
    phase = 'backup'
    try:
        populate(source, backup)
        write_new(backup.data_root/'plan.json', encode(plan))
        with freeze_files(backup):
            saved = snapshot(backup)
        require_equal(saved, plan['snapshot'])
        require(file_facts(source) == plan['snapshot']['files'], 'SOURCE_CHANGED_AFTER_BACKUP')
        phase = 'stage'
        populate(backup, stage)
        with freeze_files(stage):
            staged = snapshot(stage)
        require_equal(staged, plan['snapshot'])
        manifest = {'schema_version': 1, 'plan': plan, 'backup_files': saved['files'],
                    'staged_files': staged['files'], 'source_unchanged': True, 'stage_verified': True}
        write_new(backup.data_root/'manifest.json', encode(manifest))
        phase = 'publication'
        check_writers()
        require(file_facts(source) == plan['snapshot']['files'], 'SOURCE_CHANGED_BEFORE_PUBLICATION')
        parent_check(target.data_root.parent)
        publish(stage.data_root, target.data_root)
        phase = 'post_publication_verify'
        with freeze_files(target):
            final = snapshot(target)
        require_equal(final, plan['snapshot'])
        require(final['files'] == staged['files'], 'PUBLISHED_FILE_IDENTITY_MISMATCH')
        require(file_facts(source) == plan['snapshot']['files'], 'SOURCE_CHANGED_AFTER_PUBLICATION')
        report = {'status': 'MIGRATED_AND_VERIFIED', 'migration_id': plan['migration_id'],
                  'target': str(target.data_root), 'backup': str(backup.data_root), 'stage': str(stage.data_root),
                  'stage_exists': stage.data_root.exists(), 'files': final['files'], 'application': final['application']}
        write_new(backup.data_root/'verification.json', encode(report))
        return report
    except BaseException as error:
        if backup.data_root.is_dir():
            try:
                write_new(backup.data_root/'failure.json', encode({'phase': phase, 'error_type': type(error).__name__,
                    'target': str(target.data_root), 'backup': str(backup.data_root), 'stage': str(stage.data_root),
                    'target_exists': target.data_root.exists(), 'stage_exists': stage.data_root.exists(),
                    'action': 'STOPPED_ALL_ARTIFACTS_RETAINED_NO_AUTOMATIC_ROLLBACK'}))
            except Exception:
                pass
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--verify', action='store_true')
    parser.add_argument('--migration-id')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--writers-stopped', action='store_true')
    parser.add_argument('--unrelated-pid', action='append', type=int, default=[])
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args(argv)
    context = {}
    try:
        require(os.name == 'nt', 'WINDOWS_REQUIRED')
        git = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', str(ROOT),
                              'rev-parse', '--show-toplevel', 'HEAD'], capture_output=True, text=True, check=False)
        require(git.returncode == 0 and git.stdout.splitlines() == [ROOT.as_posix(), APPROVED_HEAD], 'PROJECT_GIT_BASELINE_MISMATCH')
        diff = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', str(ROOT),
                               'diff', '--quiet', 'HEAD', '--', 'apps', 'scripts/dev'], check=False)
        require(diff.returncode == 0, 'TRACKED_APPLICATION_CHANGES_STOP_FOR_REVIEW')
        known_base = inspect_processes(set(args.unrelated_pid))
        target = ManagementPaths.resolve(ROOT, user_data=True)
        context['target'] = str(target.data_root)
        require(os.path.normcase(str(target.data_root.parent)) == os.path.normcase(known_base), 'LOCALAPPDATA_IDENTITY_MISMATCH')
        parent_error = None
        try:
            parent_check(target.data_root.parent)
        except secure_files.SecureFileError:
            parent_error = 'ENV_PERMISSION_ERROR'
        if args.verify:
            require(parent_error is None, 'ENV_PERMISSION_ERROR')
            require(args.manifest is not None, 'MANIFEST_REQUIRED')
            manifest_path = Path(os.path.abspath(args.manifest))
            require(manifest_path.name == 'manifest.json' and manifest_path.parent.parent == target.data_root.parent
                    and re.fullmatch(r'FisheryManagement\.mig4b-backup-[0-9TZ-]+-[a-f0-9]{12}', manifest_path.parent.name),
                    'MANIFEST_PATH_NOT_AUTHORIZED')
            safe_path(manifest_path); secure_files.inspect_policy(manifest_path)
            require(manifest_path.stat().st_size <= 1024*1024, 'MANIFEST_TOO_LARGE')
            manifest = json.loads(manifest_path.read_bytes())
            require(manifest['plan']['target'] == str(target.data_root), 'MANIFEST_TARGET_MISMATCH')
            with freeze_files(target):
                final = snapshot(target)
            require_equal(final, manifest['plan']['snapshot'])
            require(final['files'] == manifest['staged_files'], 'PUBLISHED_FILE_IDENTITY_MISMATCH')
            print(encode({'status': 'VERIFIED_READ_ONLY', 'application': final['application'], 'files': final['files']}).decode())
            return 0
        require(not os.path.lexists(target.data_root), 'TARGET_ALREADY_EXISTS')
        operation = args.migration_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:12]
        require(re.fullmatch(r'[0-9TZ-]+-[a-f0-9]{12}', operation) is not None, 'INVALID_MIGRATION_ID')
        source = ManagementPaths.resolve(SOURCE)
        with freeze_files(source):
            frozen = snapshot(source)
            require({name: info['sha256'] for name, info in frozen['files'].items()} == BASELINE, 'SOURCE_CHANGED_SINCE_MIG4A_STOP_FOR_APPROVAL')
            plan = {'schema_version': 1, 'migration_id': operation, 'approved_head': APPROVED_HEAD,
                    'script_sha256': sha(Path(__file__)), 'source': str(SOURCE), 'target': str(target.data_root),
                    'backup': str(target.data_root.with_name('FisheryManagement.mig4b-backup-'+operation)),
                    'stage': str(target.data_root.with_name('FisheryManagement.mig4b-stage-'+operation)), 'snapshot': frozen}
            plan_hash = hashlib.sha256(encode(plan)).hexdigest()
            context.update(migration_id=operation, backup=plan['backup'], stage=plan['stage'])
            if not args.apply:
                print(encode({'status': 'DRY_RUN_READY' if parent_error is None else 'DRY_RUN_BLOCKED_ENV',
                              'parent_policy': parent_error or 'PASS', 'plan_sha256': plan_hash, 'plan': plan}).decode())
                return 0 if parent_error is None else 2
            require(parent_error is None, 'ENV_PERMISSION_ERROR_USE_NORMAL_POWERSHELL')
            require(args.writers_stopped, 'WRITERS_STOPPED_CONFIRMATION_REQUIRED')
            require(args.migration_id is not None and args.plan_sha256 == plan_hash, 'APPROVED_PLAN_MISMATCH_RERUN_DRY_RUN')
            result = execute(plan, source, target, lambda: inspect_processes(set(args.unrelated_pid)))
            print(encode(result).decode())
            return 0
    except (Exception, KeyboardInterrupt) as error:
        code = str(error) if isinstance(error, MigrationError) else getattr(error, 'code', None) or type(error).__name__
        print(encode({'status': 'STOPPED', 'code': code, 'action': 'NO_CLEANUP_NO_ROLLBACK', **context}).decode())
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
