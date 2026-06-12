"""Extractor registry — the Open/Closed seam.

Adding a language means registering an Extractor here; the orchestrator and
every other module stay untouched. Dispatch picks the first extractor that
`supports()` a file, so order = priority.
"""

from __future__ import annotations

from ..domain.models import Fragment, SourceFile
from ..domain.ports import Extractor

_REGISTRY: list[Extractor] = []


def register(extractor: Extractor) -> Extractor:
    """Register an extractor. Usable as a decorator on a class instance factory."""
    _REGISTRY.append(extractor)
    return extractor


def registered() -> list[Extractor]:
    return list(_REGISTRY)


def extract_one(file: SourceFile) -> Fragment:
    """Dispatch a file to the first supporting extractor.

    This is the function handed to the Scheduler, so it must be importable at
    module level (picklable for the process pool).
    """
    for extractor in _REGISTRY:
        if extractor.supports(file):
            return extractor.extract(file)
    # No extractor: emit an empty fragment so the file still counts as 'seen'.
    return Fragment(path=file.path, fingerprint=file.fingerprint)
