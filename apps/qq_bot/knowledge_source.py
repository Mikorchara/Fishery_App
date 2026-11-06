"""Read-only Knowledge composition for an explicitly selected Monitoring instance."""
from pathlib import Path

from apps.knowledge.repository import KnowledgeRepository
from apps.knowledge.service import KnowledgeContentService
from apps.management_paths import ManagementPaths
from .contracts import BotError
from .monitoring_source import MonitoringSourceConfig


def open_readonly_knowledge(config):
    """No directory discovery, initialization, migration or alternate source."""
    if type(config) is not MonitoringSourceConfig:
        raise BotError('EXPLICIT_MONITORING_SOURCE_REQUIRED')
    root = config.data_root
    if not isinstance(root, Path) or not root.is_absolute():
        raise BotError('EXPLICIT_MONITORING_SOURCE_REQUIRED')
    paths = ManagementPaths.resolve(Path(__file__).resolve().parents[2], data_root=root)
    return KnowledgeContentService(KnowledgeRepository(paths.knowledge,
        require_existing=True, read_only=True))
