"""Explicit first-install background corpus; normal startup never loads it.

The bundled text is project reference material, not a professional aquaculture
standard or evidence of current pond conditions. Existing user stores are never
opened, merged or replaced by this initializer.
"""
import hashlib
from importlib.resources import as_file, files
from pathlib import Path

from .migration import migrate
from .repository import KnowledgeError


INITIAL_KNOWLEDGE_VERSION = 'management-initial-knowledge@1'
RESOURCE_SHA256 = '6aa00314094b3660bb3ef62bf856976c9e7cfb85ead88a7a8f4c388a636c012e'


def initialize_initial_knowledge(path):
    """Create a new authoritative SQLite from the shipped, non-user corpus."""
    target = Path(path)
    if target.exists():
        raise KnowledgeError('KNOWLEDGE_INITIAL_TARGET_EXISTS')
    resource = files('apps.knowledge').joinpath('resources/eel_knowledge_v1.json')
    try:
        with as_file(resource) as source:
            if hashlib.sha256(source.read_bytes()).hexdigest() != RESOURCE_SHA256:
                raise KnowledgeError('KNOWLEDGE_INITIAL_RESOURCE_CHANGED')
            plan = migrate(None, target, source)
            return migrate(None, target, source, apply=True,
                           approved_plan_sha256=plan['plan_sha256'])
    except OSError:
        raise KnowledgeError('KNOWLEDGE_INITIAL_RESOURCE_UNAVAILABLE') from None
