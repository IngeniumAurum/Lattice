"""FingerprintCache adapter — per-file incremental caching.

The key is a fast content hash plus size/mtime. A re-run only re-extracts files
whose fingerprint changed, so cost scales with the diff, not the repo. graphify
reprocesses the corpus; this skips ~everything unchanged.
"""

from __future__ import annotations

import hashlib
import os

from ..domain.models import Fragment, SourceFile

_CHUNK = 1 << 20  # 1 MiB streaming read — bounded memory for large files.


def compute_fingerprint(path: str) -> str:
    """blake2b over content, salted with size + mtime for cheap invalidation."""
    st = os.stat(path)
    h = hashlib.blake2b(digest_size=16)
    h.update(f"{st.st_size}:{int(st.st_mtime)}:".encode())
    with open(path, "rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


class InMemoryFingerprintCache:
    """Reference cache. Swap for a sqlite/disk adapter via the same port."""

    def __init__(self) -> None:
        self._by_path: dict[str, Fragment] = {}

    def get(self, file: SourceFile) -> Fragment | None:
        cached = self._by_path.get(file.path)
        if cached is not None and cached.fingerprint == file.fingerprint:
            return cached
        return None

    def put(self, fragment: Fragment) -> None:
        self._by_path[fragment.path] = fragment
