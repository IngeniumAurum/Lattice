"""Higher-quality community detection via the Leiden algorithm.

Same `detect(snapshot) -> dict[str, int]` contract as `community.detect`, so it
is a drop-in substitute (Liskov) — the CLI can pick it when the optional
`igraph`/`leidenalg` extra is installed. Leiden guarantees well-connected
communities and typically beats the built-in Louvain pass on modularity, at the
cost of an external dependency.

If the extra is missing, `detect()` raises `LeidenUnavailable`; callers should
catch it and fall back to `community.detect`.
"""

from __future__ import annotations

from ..domain.models import GraphSnapshot


class LeidenUnavailable(RuntimeError):
    """Raised when igraph/leidenalg are not installed."""


def available() -> bool:
    try:
        import igraph  # noqa: F401
        import leidenalg  # noqa: F401
        return True
    except Exception:
        return False


def detect(snapshot: GraphSnapshot, resolution: float = 1.0) -> dict[str, int]:
    try:
        import igraph as ig
        import leidenalg as la
    except Exception as exc:  # pragma: no cover - exercised only without extra
        raise LeidenUnavailable(
            "install the 'leiden' extra: pip install 'lattice[leiden]'") from exc

    order = snapshot.order
    if not order:
        return {}
    index = {nid: i for i, nid in enumerate(order)}

    # Collapse to a simple undirected edge set keyed by node index.
    seen: set[tuple[int, int]] = set()
    for i, nid in enumerate(order):
        for j in snapshot.indices[snapshot.indptr[i]:snapshot.indptr[i + 1]]:
            a, b = (i, j) if i < j else (j, i)
            if a != b:
                seen.add((a, b))

    graph = ig.Graph(n=len(order), edges=list(seen), directed=False)
    partition = la.find_partition(
        graph, la.RBConfigurationVertexPartition, resolution_parameter=resolution)

    membership = partition.membership  # node index -> community id
    return {order[i]: membership[i] for i in range(len(order))}
