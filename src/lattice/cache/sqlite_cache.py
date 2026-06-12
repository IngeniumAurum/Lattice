"""Persistent FingerprintCache backed by SQLite.

Same `FingerprintCache` port as `InMemoryFingerprintCache` (Liskov), so swapping
it in is a one-line change at the composition root. Fragments survive across
process invocations, so a cold re-run still only re-extracts files whose content
fingerprint changed — incrementality that outlives a single command.

Serialization is plain JSON keyed by path; the stored fingerprint gates reuse.
"""

from __future__ import annotations

import json
import sqlite3

from ..domain.models import Confidence, Edge, Fragment, Node


def _fragment_to_json(fragment: Fragment) -> str:
    return json.dumps({
        "nodes": [
            {"id": n.id, "label": n.label, "kind": n.kind, "path": n.path,
             "line": n.line, "meta": n.meta}
            for n in fragment.nodes
        ],
        "edges": [
            {"source": e.source, "target": e.target, "relation": e.relation,
             "confidence": e.confidence.value, "weight": e.weight}
            for e in fragment.edges
        ],
    })


def _fragment_from_json(path: str, fingerprint: str, blob: str) -> Fragment:
    data = json.loads(blob)
    nodes = [Node(id=n["id"], label=n["label"], kind=n["kind"], path=n["path"],
                  line=n["line"], meta=n.get("meta", {}))
             for n in data["nodes"]]
    edges = [Edge(e["source"], e["target"], e["relation"],
                  confidence=Confidence(e["confidence"]), weight=e["weight"])
             for e in data["edges"]]
    return Fragment(path=path, fingerprint=fingerprint, nodes=nodes, edges=edges)


class SqliteFingerprintCache:
    def __init__(self, db_path: str = "lattice.cache.db") -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS fragments ("
            "path TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, blob TEXT NOT NULL)"
        )
        self._conn.commit()

    def get(self, file) -> Fragment | None:
        row = self._conn.execute(
            "SELECT fingerprint, blob FROM fragments WHERE path = ?",
            (file.path,),
        ).fetchone()
        if row is None or row[0] != file.fingerprint:
            return None
        return _fragment_from_json(file.path, row[0], row[1])

    def put(self, fragment: Fragment) -> None:
        self._conn.execute(
            "INSERT INTO fragments(path, fingerprint, blob) VALUES(?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET fingerprint=excluded.fingerprint, "
            "blob=excluded.blob",
            (fragment.path, fragment.fingerprint, _fragment_to_json(fragment)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
