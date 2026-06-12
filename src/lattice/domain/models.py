"""Pure domain entities — no I/O, no third-party dependencies.

These are the only data structures that cross port boundaries. Keeping them
dependency-free is what lets every adapter (parser, store, renderer, cache)
agree on a shared vocabulary without coupling to each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Confidence(str, Enum):
    """How sure we are that an edge is real.

    EXTRACTED  — read directly from an AST / schema (ground truth).
    INFERRED   — derived heuristically (e.g. naming convention).
    AMBIGUOUS  — plausible but unverified; rendered dimmer / filterable.
    """

    EXTRACTED = "extracted"
    INFERRED = "inferred"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class SourceFile:
    """A discovered file, before extraction. `fingerprint` keys the cache."""

    path: str
    language: str
    size: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class Node:
    """A vertex in the knowledge graph (a function, table, doc section, ...)."""

    id: str
    label: str
    kind: str
    path: str
    line: int = 0
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Edge:
    """A directed, typed, confidence-tagged relationship between two nodes."""

    source: str
    target: str
    relation: str
    confidence: Confidence = Confidence.EXTRACTED
    weight: float = 1.0


@dataclass(slots=True)
class Fragment:
    """The unit of work: one file's full contribution to the graph.

    Fragments are self-contained, which makes them (a) parallelizable — workers
    produce them independently, (b) cacheable — keyed by file fingerprint, and
    (c) mergeable — assembling fragments is order-independent.
    """

    path: str
    fingerprint: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    """An immutable, query-optimized view of the whole graph (CSR-backed)."""

    nodes: dict[str, Node]
    # CSR triplet: indptr[i]..indptr[i+1] indexes into `indices`/`edges`.
    order: list[str]
    indptr: list[int]
    indices: list[int]
    edges: list[Edge]

    def neighbors(self, node_id: str) -> list[str]:
        """Adjacent node ids via a contiguous CSR slice — no per-edge hops."""
        try:
            i = self.order.index(node_id)
        except ValueError:
            return []
        start, end = self.indptr[i], self.indptr[i + 1]
        return [self.order[j] for j in self.indices[start:end]]
