"""Scheduler adapters — pluggable execution strategies.

Extraction is CPU-bound and per-file independent, so it parallelizes cleanly.
The orchestrator depends on the Scheduler port and cannot tell which strategy it
received (Liskov), so tests use SerialScheduler and production uses the pool.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Callable, Iterable

from ..domain.models import Fragment, SourceFile


class SerialScheduler:
    """Deterministic, single-process — ideal for tests and debugging."""

    def map(self, fn: Callable[[SourceFile], Fragment],
            items: Iterable[SourceFile]) -> Iterable[Fragment]:
        for item in items:
            yield fn(item)


class ProcessPoolScheduler:
    """Fan extraction across cores. Results stream back as they complete."""

    def __init__(self, max_workers: int | None = None,
                 chunksize: int = 8) -> None:
        self._max_workers = max_workers
        self._chunksize = chunksize

    def map(self, fn: Callable[[SourceFile], Fragment],
            items: Iterable[SourceFile]) -> Iterable[Fragment]:
        with ProcessPoolExecutor(max_workers=self._max_workers) as pool:
            # unordered would be faster, but ordered keeps output deterministic.
            yield from pool.map(fn, list(items), chunksize=self._chunksize)
