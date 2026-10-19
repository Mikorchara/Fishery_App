"""Source-only qualification corpus; never used by normal Web/runtime loading."""
from pathlib import Path

from apps.knowledge.migration import legacy_reference


def reference_knowledge():
    # The existing public, frozen test corpus is byte-identical to the original
    # qualification input. No old package/resource lookup or user data fallback.
    path = Path(__file__).resolve().parents[2] / 'knowledge/tests/fixtures/eel_knowledge_v1.json'
    return legacy_reference(path)
