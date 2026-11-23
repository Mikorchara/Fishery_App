"""Explicit first-install background corpus; normal startup never loads it.

The bundled text is project reference material, not a professional aquaculture
standard or evidence of current pond conditions. Existing user stores are never
opened, merged or replaced by this initializer.
"""
from decimal import Decimal, InvalidOperation
import hashlib
from importlib.resources import as_file, files
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from .migration import migrate
from .repository import MAX_IMPORTED_RECORDS, MAX_TOTAL_BODY_CHARS, KnowledgeError, KnowledgeRepository, identifier
from .service import CATEGORIES, content, text


INITIAL_KNOWLEDGE_VERSION = 'management-initial-knowledge@1'
RESOURCE_SHA256 = '6aa00314094b3660bb3ef62bf856976c9e7cfb85ead88a7a8f4c388a636c012e'
LEGACY_KNOWLEDGE_SEED = 'legacy'
CURATED_KNOWLEDGE_SEED = 'curated-oxygen'
CURATED_KNOWLEDGE_VERSION = 'eel-oxygen-feeding@1'
CURATED_KNOWLEDGE_METADATA = 'curated_oxygen'
INITIAL_RESOURCES = {
    LEGACY_KNOWLEDGE_SEED: 'resources/eel_knowledge_v1.json',
    CURATED_KNOWLEDGE_SEED: 'resources/eel_oxygen_feeding_v1.json',
}


def initialize_initial_knowledge(path):
    """Create a new authoritative SQLite from the shipped, non-user corpus."""
    target = Path(path)
    if target.exists():
        raise KnowledgeError('KNOWLEDGE_INITIAL_TARGET_EXISTS')
    resource = files('apps.knowledge').joinpath(INITIAL_RESOURCES[LEGACY_KNOWLEDGE_SEED])
    try:
        with as_file(resource) as source:
            if hashlib.sha256(source.read_bytes()).hexdigest() != RESOURCE_SHA256:
                raise KnowledgeError('KNOWLEDGE_INITIAL_RESOURCE_CHANGED')
            plan = migrate(None, target, source)
            return migrate(None, target, source, apply=True,
                           approved_plan_sha256=plan['plan_sha256'])
    except OSError:
        raise KnowledgeError('KNOWLEDGE_INITIAL_RESOURCE_UNAVAILABLE') from None


_CARD_FIELDS = {
    'id', 'title', 'body', 'source_url', 'source_version', 'keywords',
    'species', 'outcomes', 'oxygen_intervals',
}
_INTERVAL_FIELDS = {'low', 'high', 'low_inclusive', 'high_inclusive'}
_OUTCOMES = {'feeding', 'growth', 'context'}


def _oxygen_bound(value):
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 32:
        raise ValueError()
    bound = Decimal(value)
    if not bound.is_finite() or bound < 0:
        raise ValueError()
    return bound


def _validate_interval(interval):
    if (not isinstance(interval, dict) or set(interval) != _INTERVAL_FIELDS
            or any(type(interval[key]) is not bool for key in ('low_inclusive', 'high_inclusive'))):
        raise ValueError()
    low, high = (_oxygen_bound(interval[key]) for key in ('low', 'high'))
    if low is None and high is None:
        raise ValueError()
    if low is not None and high is not None and (
            low > high or low == high and not (interval['low_inclusive'] and interval['high_inclusive'])):
        raise ValueError()


def _record_from_card(card, ordinal):
    if not isinstance(card, dict) or set(card) != _CARD_FIELDS or card['species'] != 'anguilla_japonica':
        raise ValueError()
    key = identifier(card['id'])
    if not key.startswith('builtin-'):
        raise ValueError()
    outcomes = card['outcomes']
    if (not isinstance(outcomes, list) or not outcomes or any(
            not isinstance(item, str) or item not in _OUTCOMES for item in outcomes)):
        raise ValueError()
    keywords, intervals = card['keywords'], card['oxygen_intervals']
    if not isinstance(keywords, list) or not keywords or not isinstance(intervals, list):
        raise ValueError()
    for keyword in keywords:
        text(keyword, 120)
    for interval in intervals:
        _validate_interval(interval)
    source = text(card['source_url'], 512)
    parsed_source = urlsplit(source)
    if parsed_source.scheme != 'https' or not parsed_source.hostname or parsed_source.username is not None:
        raise ValueError()
    source_version = text(card['source_version'], 120)
    chunk_type = 'feeding' if 'feeding' in outcomes else 'life_cycle' if 'growth' in outcomes else 'water_quality'
    values = content({'title': card['title'], 'category': CATEGORIES[chunk_type], 'body': card['body']})
    if (values['title'] != card['title'] or values['body'] != card['body']
            or source != card['source_url'] or source_version != card['source_version']):
        raise ValueError()
    return {
        **values, 'id': key, 'evidence_id': key, 'version': 1, 'status': 'ACTIVE', 'origin': 'builtin',
        'updated_at': None, 'source_id': source, 'source_version': source_version,
        'original_source_id': source, 'original_source_version': source_version,
        'chunk_type': chunk_type, 'keywords': keywords, 'text_style': 'body', 'ordinal': ordinal,
    }


def _read_curated_corpus():
    resource = files('apps.knowledge').joinpath(INITIAL_RESOURCES[CURATED_KNOWLEDGE_SEED])
    try:
        corpus = json.loads(resource.read_text(encoding='utf-8'))
    except OSError:
        raise KnowledgeError('KNOWLEDGE_INITIAL_RESOURCE_UNAVAILABLE') from None
    except (ValueError, UnicodeError):
        raise KnowledgeError('KNOWLEDGE_CURATED_RESOURCE_INVALID') from None
    try:
        if (not isinstance(corpus, dict) or set(corpus) != {'version', 'records'}
                or corpus['version'] != CURATED_KNOWLEDGE_VERSION or not isinstance(corpus['records'], list)
                or not 1 <= len(corpus['records']) <= MAX_IMPORTED_RECORDS):
            raise ValueError()
        rows = [_record_from_card(card, ordinal) for ordinal, card in enumerate(corpus['records'])]
        if len({row['id'] for row in rows}) != len(rows) or sum(len(row['body']) for row in rows) > MAX_TOTAL_BODY_CHARS:
            raise ValueError()
    except (ValueError, TypeError, InvalidOperation):
        raise KnowledgeError('KNOWLEDGE_CURATED_RESOURCE_INVALID') from None
    return corpus, rows


def initialize_curated_knowledge(path):
    """Publish the reference corpus to a new SQLite file without opening any existing target."""
    target = Path(path)
    if os.path.lexists(target):
        raise KnowledgeError('KNOWLEDGE_INITIAL_TARGET_EXISTS')
    corpus, rows = _read_curated_corpus()
    try:
        with TemporaryDirectory(prefix='.curated-knowledge-', dir=target.parent) as directory:
            stage = Path(directory) / 'knowledge.sqlite3'
            repository = KnowledgeRepository(stage)
            with repository.connection(write=True) as db:
                for row in rows:
                    repository.insert(db, row)
                db.executemany('INSERT INTO knowledge_metadata VALUES (?,?)', [
                    ('migration_version', 'unified-knowledge@2'),
                    (CURATED_KNOWLEDGE_METADATA, json.dumps(corpus, ensure_ascii=False, allow_nan=False)),
                ])
            # Reopen as a normal read-only instance before no-replace publication.
            _, actual, metadata = KnowledgeRepository(stage, read_only=True).snapshot()
            if actual != rows or json.loads(metadata[CURATED_KNOWLEDGE_METADATA]) != corpus:
                raise KnowledgeError('KNOWLEDGE_CURATED_VERIFY_FAILED')
            os.link(stage, target)
    except FileExistsError:
        raise KnowledgeError('KNOWLEDGE_INITIAL_TARGET_EXISTS') from None
    except OSError:
        raise KnowledgeError('KNOWLEDGE_STORAGE_ERROR') from None
    return {'builtin_count': len(rows)}
