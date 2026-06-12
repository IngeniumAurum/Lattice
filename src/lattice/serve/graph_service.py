"""Pure query service over a GraphSnapshot — the use case behind the MCP server.

Kept free of any transport/protocol code so it is trivially unit-testable and
reusable by other front-ends (HTTP, CLI REPL). The MCP adapter merely marshals
JSON to/from these methods.
"""

from __future__ import annotations

from ..domain.models import GraphSnapshot
from ..query.traversal import shortest_path


class GraphService:
    def __init__(self, snapshot: GraphSnapshot) -> None:
        self._snap = snapshot

    def stats(self) -> dict:
        kinds: dict[str, int] = {}
        for node in self._snap.nodes.values():
            kinds[node.kind] = kinds.get(node.kind, 0) + 1
        return {"nodes": len(self._snap.nodes),
                "edges": len(self._snap.edges), "kinds": kinds}

    def search(self, query: str, limit: int = 20) -> list[dict]:
        q = query.lower()
        hits = [n for n in self._snap.nodes.values() if q in n.label.lower()]
        hits.sort(key=lambda n: (len(n.label), n.label))
        return [{"id": n.id, "label": n.label, "kind": n.kind,
                 "path": n.path, "line": n.line} for n in hits[:limit]]

    def neighbors(self, node_id: str) -> list[dict]:
        out = []
        for nid in self._snap.neighbors(node_id):
            node = self._snap.nodes.get(nid)
            if node is not None:
                out.append({"id": node.id, "label": node.label,
                            "kind": node.kind})
        return out

    def path(self, src: str, dst: str) -> list[str]:
        return shortest_path(self._snap, src, dst)
