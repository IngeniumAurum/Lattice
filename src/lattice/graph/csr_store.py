"""GraphStore adapter — incremental writes, CSR reads.

Write path: fragments accumulate into compact adjacency lists. This is O(1)
amortized per edge and order-independent, so fragments from parallel workers
merge in any order.

Read path: `snapshot()` compiles to the Compressed Sparse Row layout — three
flat arrays. Neighbor iteration is then a contiguous slice (cache-friendly,
allocation-free), versus NetworkX's dict-of-dicts hop per edge.
"""

from __future__ import annotations

from ..domain.models import Edge, Fragment, GraphSnapshot, Node


class CsrGraphStore:
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._adj: dict[str, list[Edge]] = {}

    def add(self, fragment: Fragment) -> None:
        for node in fragment.nodes:
            # First writer wins for node identity; later ones could merge meta.
            self._nodes.setdefault(node.id, node)
        for edge in fragment.edges:
            self._adj.setdefault(edge.source, []).append(edge)
            # Ensure endpoints exist as (possibly placeholder) nodes.
            self._nodes.setdefault(
                edge.target,
                Node(id=edge.target, label=edge.target, kind="external",
                     path=""),
            )
            self._adj.setdefault(edge.target, self._adj.get(edge.target, []))

    def snapshot(self) -> GraphSnapshot:
        order = list(self._nodes.keys())
        index = {node_id: i for i, node_id in enumerate(order)}

        indptr = [0]
        indices: list[int] = []
        edges: list[Edge] = []
        for node_id in order:
            for edge in self._adj.get(node_id, ()):
                indices.append(index[edge.target])
                edges.append(edge)
            indptr.append(len(indices))

        return GraphSnapshot(
            nodes=dict(self._nodes),
            order=order,
            indptr=indptr,
            indices=indices,
            edges=edges,
        )
