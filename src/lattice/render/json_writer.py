"""Renderer adapter — JSON export. Reference for the Renderer port.

Other formats (HTML, Mermaid, GraphML) implement the same `render()` contract
and register independently — Open/Closed for outputs.
"""

from __future__ import annotations

import json

from ..domain.models import GraphSnapshot


class JsonRenderer:
    def __init__(self, indent: int | None = 2) -> None:
        self._indent = indent

    def render(self, snapshot: GraphSnapshot, out_path: str) -> str:
        payload = {
            "nodes": [
                {"id": n.id, "label": n.label, "kind": n.kind,
                 "path": n.path, "line": n.line, "meta": n.meta}
                for n in snapshot.nodes.values()
            ],
            "edges": [
                {"source": e.source, "target": e.target, "relation": e.relation,
                 "confidence": e.confidence.value, "weight": e.weight}
                for e in snapshot.edges
            ],
            "stats": {
                "node_count": len(snapshot.nodes),
                "edge_count": len(snapshot.edges),
            },
        }
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=self._indent)
        return out_path
