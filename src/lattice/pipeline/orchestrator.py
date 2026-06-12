"""The use case: discover → cache-filter → parallel extract → assemble → snapshot.

Depends ONLY on domain ports. No adapter is imported here, so the whole pipeline
is testable with fakes and reconfigurable without edits (Dependency Inversion).
"""

from __future__ import annotations

from typing import Callable

from ..domain.models import Fragment, GraphSnapshot, SourceFile
from ..domain.ports import (
    Enricher,
    FingerprintCache,
    GraphStore,
    Scheduler,
    SourceDiscovery,
)


class Pipeline:
    def __init__(
        self,
        discovery: SourceDiscovery,
        scheduler: Scheduler,
        store: GraphStore,
        extract_fn: Callable[[SourceFile], Fragment],
        cache: FingerprintCache | None = None,
        enricher: Enricher | None = None,
    ) -> None:
        self._discovery = discovery
        self._scheduler = scheduler
        self._store = store
        self._extract_fn = extract_fn
        self._cache = cache
        self._enricher = enricher

    def run(self, root: str) -> GraphSnapshot:
        files = list(self._discovery.walk(root))

        # Split on the cache so only changed files reach the (costly) pool.
        reused: list[Fragment] = []
        to_extract: list[SourceFile] = []
        for f in files:
            hit = self._cache.get(f) if self._cache else None
            (reused.append(hit) if hit is not None else to_extract.append(f))

        fresh = list(self._scheduler.map(self._extract_fn, to_extract))
        if self._cache:
            for frag in fresh:
                self._cache.put(frag)

        fragments: list[Fragment] = reused + fresh
        if self._enricher is not None:
            fragments = list(self._enricher.enrich(fragments))

        for frag in fragments:
            self._store.add(frag)
        return self._store.snapshot()
