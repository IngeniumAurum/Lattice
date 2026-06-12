"""Graph queries over the CSR snapshot — BFS reachability and shortest path.

Runs directly on the flat CSR arrays, so traversal touches contiguous memory
instead of chasing nested dicts.
"""

from __future__ import annotations

from collections import deque

from ..domain.models import GraphSnapshot


def shortest_path(snapshot: GraphSnapshot, src: str, dst: str) -> list[str]:
    """Unweighted shortest path (BFS). Returns [] if unreachable."""
    order_index = {node_id: i for i, node_id in enumerate(snapshot.order)}
    if src not in order_index or dst not in order_index:
        return []

    start = order_index[src]
    target = order_index[dst]
    prev: dict[int, int] = {start: start}
    queue: deque[int] = deque([start])

    while queue:
        i = queue.popleft()
        if i == target:
            break
        for j in snapshot.indices[snapshot.indptr[i]:snapshot.indptr[i + 1]]:
            if j not in prev:
                prev[j] = i
                queue.append(j)

    if target not in prev:
        return []

    path = [target]
    while path[-1] != start:
        path.append(prev[path[-1]])
    return [snapshot.order[i] for i in reversed(path)]
