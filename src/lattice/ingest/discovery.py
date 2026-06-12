"""SourceDiscovery adapter — a lazy, ignore-aware filesystem walk.

Yields SourceFiles one at a time so the pipeline can start extracting before the
walk finishes. Computes the fingerprint here (single read) so downstream cache
checks are free.
"""

from __future__ import annotations

import os
from typing import Iterable

from ..cache.fingerprint import compute_fingerprint
from ..domain.models import SourceFile

# Minimal language map; extractors decide what they actually support.
_LANG_BY_EXT = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".sql": "sql",
    ".md": "markdown",
}

_PRUNE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__",
               ".mypy_cache", ".pytest_cache", "dist", "build", ".tox"}


class FileSystemDiscovery:
    """Default SourceDiscovery: os.scandir-based, prunes noise directories."""

    def __init__(self, prune: set[str] | None = None) -> None:
        self._prune = prune or _PRUNE_DIRS

    def walk(self, root: str) -> Iterable[SourceFile]:
        for dirpath, dirnames, filenames in os.walk(root):
            # In-place prune so os.walk doesn't descend into ignored trees.
            dirnames[:] = [d for d in dirnames if d not in self._prune]
            for name in filenames:
                ext = os.path.splitext(name)[1].lower()
                language = _LANG_BY_EXT.get(ext)
                if language is None:
                    continue
                path = os.path.join(dirpath, name)
                try:
                    size = os.path.getsize(path)
                    fingerprint = compute_fingerprint(path)
                except OSError:
                    continue
                yield SourceFile(path=path, language=language,
                                 size=size, fingerprint=fingerprint)
