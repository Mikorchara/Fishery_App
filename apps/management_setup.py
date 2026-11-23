"""Explicit first-run setup, independent of QQ accounts and private credentials."""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from apps.knowledge.initial import CURATED_KNOWLEDGE_SEED, INITIAL_RESOURCES, LEGACY_KNOWLEDGE_SEED
from apps.management_paths import ManagementPaths
from apps.management_process import ISOLATED_MARKER_CONTRACT
from apps.management_web.__main__ import project_root
from apps.management_web.instance import InstanceError, initialize_instance, safe_path, validate_instance

ROOT = project_root()
DAILY_DIRECTORY = 'qq-m3-real-test'  # Preserve the established four-shortcut location.


def daily_root(workspace=None):
    return Path(ROOT if workspace is None else workspace).absolute() / 'outputs' / DAILY_DIRECTORY


def initialize_daily(workspace=None, *, data_root=None, knowledge_seed=LEGACY_KNOWLEDGE_SEED):
    """Publish only a NEW daily instance. Existing data is never opened or changed."""
    workspace = Path(ROOT if workspace is None else workspace).absolute()
    if data_root is None and knowledge_seed == CURATED_KNOWLEDGE_SEED:
        raise InstanceError('EXPLICIT_DATA_ROOT_REQUIRED')
    if data_root is not None and not Path(data_root).is_absolute():
        raise InstanceError('DATA_ROOT_MUST_BE_ABSOLUTE')
    destination = daily_root(workspace) if data_root is None else ManagementPaths.resolve(
        workspace, data_root=data_root).data_root
    safe_path(destination)
    if destination.exists():
        raise InstanceError('INSTANCE_ALREADY_EXISTS')
    destination.parent.mkdir(exist_ok=True)
    holder = Path(tempfile.mkdtemp(prefix='.daily-setup-', dir=destination.parent))
    try:
        paths = ManagementPaths.resolve(workspace, data_root=holder / 'instance')
        knowledge_records = initialize_instance(paths, knowledge_seed=knowledge_seed)
        # These are the existing read-only Web tools, not AI write permissions.
        from apps.ai_backend.tools import ToolRegistry
        from apps.ai_service.business_tools.registry import HISTORY_CANDIDATE_TOOL_NAMES
        from apps.ai_service.management_policy import ManagementToolPolicyStore
        from apps.ai_service.runtime.policy import UserToolPolicyStore
        policy = ManagementToolPolicyStore(paths.policy_directory,
            UserToolPolicyStore(paths.policy_directory, ToolRegistry([])))
        policy.save(HISTORY_CANDIDATE_TOOL_NAMES, expected_revision=policy.snapshot().revision)
        marker = dict(contract=ISOLATED_MARKER_CONTRACT, root=str(destination.resolve()),
                      instance_id='management-isolated', device_id='sim-pond-1', source='SIMULATOR')
        (paths.data_root / 'qq-isolated-instance.json').write_text(
            json.dumps(marker, ensure_ascii=False, indent=2), encoding='utf8')
        validate_instance(paths)
        safe_path(destination)
        if destination.exists():
            raise InstanceError('INSTANCE_ALREADY_EXISTS')
        os.rename(paths.data_root, destination)
        return dict(code='MANAGEMENT_DAILY_INSTANCE_CREATED', data_root=str(destination),
                    knowledge_records=knowledge_records, monitoring_observations=0, qq_configured=False,
                    credential_checked=False, network_requests=0)
    finally:
        # holder is owned by this invocation and is never an existing instance.
        if holder.parent != destination.parent or not holder.name.startswith('.daily-setup-'):
            raise InstanceError('INSTANCE_UNSAFE_PATH')
        safe_path(holder)
        shutil.rmtree(holder)


def main(argv=None):
    parser = argparse.ArgumentParser(description='首次初始化日常实例；不需要QQ或模型密钥，不联网')
    parser.add_argument('--check', action='store_true', help='Metadata only; no database or credential reads')
    parser.add_argument('--data-root', type=Path, help='明确指定新实例的绝对目录')
    parser.add_argument('--knowledge-seed', choices=INITIAL_RESOURCES, default=LEGACY_KNOWLEDGE_SEED,
                        help='首次初始化使用的资料集，curated-oxygen 需要明确的新目录')
    args = parser.parse_args(argv)
    try:
        if args.data_root is None and args.knowledge_seed == CURATED_KNOWLEDGE_SEED:
            raise InstanceError('EXPLICIT_DATA_ROOT_REQUIRED')
        if args.data_root is not None and not args.data_root.is_absolute():
            raise InstanceError('DATA_ROOT_MUST_BE_ABSOLUTE')
        if args.check:
            from importlib.resources import files
            resource = files('apps.knowledge').joinpath(INITIAL_RESOURCES[args.knowledge_seed])
            destination = daily_root() if args.data_root is None else ManagementPaths.resolve(
                ROOT, data_root=args.data_root).data_root
            result = dict(code='MANAGEMENT_SETUP_CHECKED', data_root=str(destination),
                          data_directory_exists=destination.exists(),
                          initial_knowledge_available=resource.is_file(),
                          credential_checked=False, database_opened=False, network_requests=0)
        else:
            result = initialize_daily(data_root=args.data_root, knowledge_seed=args.knowledge_seed)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except (InstanceError, OSError) as error:
        print(json.dumps(dict(code=getattr(error, 'code', 'MANAGEMENT_SETUP_STORAGE_ERROR'))), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
