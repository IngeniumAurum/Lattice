"""Ports — the narrow interfaces the pipeline depends on (Dependency Inversion).

Every concrete adapter implements one of these `Protocol`s. The orchestrator
imports *only* this module from the outer layers, so business logic never sees
tree-sitter, NetworkX, or any LLM SDK. Interfaces are deliberately small
(Interface Segregation): an Extractor knows nothing of graphs, a Renderer
nothing of caches.
"""

from __future__ import annotations

from typing import Callable, Iterable, Protocol, runtime_checkable

from .models import Fragment, GraphSnapshot, SourceFile


@runtime_checkable
class SourceDiscovery(Protocol):
    """Walk a root and stream discovered files lazily."""

    def walk(self, root: str) -> Iterable[SourceFile]: ...


@runtime_checkable
class Extractor(Protocol):
    """Turn a single file into a Fragment. One implementation per language."""

    name: str

    def supports(self, file: SourceFile) -> bool: ...

    def extract(self, file: SourceFile) -> Fragment: ...


@runtime_checkable
class FingerprintCache(Protocol):
    """Per-file incremental cache keyed by content fingerprint."""

    def get(self, file: SourceFile) -> Fragment | None: ...

    def put(self, fragment: Fragment) -> None: ...


@runtime_checkable
class Scheduler(Protocol):
    """Execution strategy for a batch of work (process pool, serial, async)."""

    def map(self, fn: Callable[[SourceFile], Fragment],
            items: Iterable[SourceFile]) -> Iterable[Fragment]: ...


@runtime_checkable
class GraphStore(Protocol):
    """Incremental write model; compiles to an immutable CSR snapshot."""

    def add(self, fragment: Fragment) -> None: ...

    def snapshot(self) -> GraphSnapshot: ...


@runtime_checkable
class Enricher(Protocol):
    """Optional LLM/semantic pass over fragments (provider-agnostic)."""

    def enrich(self, fragments: Iterable[Fragment]) -> Iterable[Fragment]: ...


@runtime_checkable
class Renderer(Protocol):
    """Serialize a snapshot to some output format. One per format."""

    def render(self, snapshot: GraphSnapshot, out_path: str) -> str: ...
