"""Neo4j-backed GraphStore adapter.

Implements the same `GraphStore` port as `CsrGraphStore` (Liskov), so the
composition root can persist to Neo4j instead of building an in-memory CSR graph
— without touching extraction, querying, or rendering. Writes are batched with
`UNWIND` + `MERGE` for idempotency; `snapshot()` streams the graph back and
compiles a CSR view so the rest of the pipeline (queries, renderers) is unchanged.

Requires the optional `neo4j` extra. Importing this module is safe regardless;
construction fails fast with a clear message if the driver is absent.
"""

from __future__ import annotations

from ..domain.models import Confidence, Edge, Fragment, GraphSnapshot, Node


class Neo4jGraphStore:
    def __init__(self, uri: str, user: str, password: str,
                 database: str = "neo4j", batch_size: int = 1000) -> None:
        try:
            from neo4j import GraphDatabase  # type: ignore
        except Exception as exc:  # pragma: no cover - exercised only without extra
            raise RuntimeError(
                "install the 'neo4j' extra: pip install 'lattice[neo4j]'") from exc
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._database = database
        self._batch = batch_size
        self._node_buf: list[Node] = []
        self._edge_buf: list[Edge] = []

    def add(self, fragment: Fragment) -> None:
        self._node_buf.extend(fragment.nodes)
        self._edge_buf.extend(fragment.edges)
        if len(self._node_buf) >= self._batch or len(self._edge_buf) >= self._batch:
            self._flush()

    def _flush(self) -> None:
        if not self._node_buf and not self._edge_buf:
            return
        nodes = [{"id": n.id, "label": n.label, "kind": n.kind,
                  "path": n.path, "line": n.line} for n in self._node_buf]
        edges = [{"s": e.source, "t": e.target, "rel": e.relation,
                  "conf": e.confidence.value, "w": e.weight}
                 for e in self._edge_buf]
        with self._driver.session(database=self._database) as session:
            if nodes:
                session.run(
                    "UNWIND $rows AS r MERGE (n:Symbol {id: r.id}) "
                    "SET n.label=r.label, n.kind=r.kind, n.path=r.path, "
                    "n.line=r.line", rows=nodes)
            if edges:
                session.run(
                    "UNWIND $rows AS r "
                    "MERGE (a:Symbol {id: r.s}) MERGE (b:Symbol {id: r.t}) "
                    "MERGE (a)-[e:REL {relation: r.rel}]->(b) "
                    "SET e.confidence=r.conf, e.weight=r.w", rows=edges)
        self._node_buf.clear()
        self._edge_buf.clear()

    def snapshot(self) -> GraphSnapshot:
        self._flush()
        nodes: dict[str, Node] = {}
        adj: dict[str, list[Edge]] = {}
        with self._driver.session(database=self._database) as session:
            for rec in session.run(
                    "MATCH (n:Symbol) RETURN n.id AS id, n.label AS label, "
                    "n.kind AS kind, n.path AS path, n.line AS line"):
                nodes[rec["id"]] = Node(id=rec["id"], label=rec["label"],
                                        kind=rec["kind"], path=rec["path"] or "",
                                        line=rec["line"] or 0)
            for rec in session.run(
                    "MATCH (a:Symbol)-[e:REL]->(b:Symbol) RETURN a.id AS s, "
                    "b.id AS t, e.relation AS rel, e.confidence AS conf, "
                    "e.weight AS w"):
                edge = Edge(rec["s"], rec["t"], rec["rel"],
                            confidence=Confidence(rec["conf"]),
                            weight=rec["w"] or 1.0)
                adj.setdefault(rec["s"], []).append(edge)

        order = list(nodes.keys())
        index = {nid: i for i, nid in enumerate(order)}
        indptr, indices, edges = [0], [], []
        for nid in order:
            for edge in adj.get(nid, ()):
                if edge.target in index:
                    indices.append(index[edge.target])
                    edges.append(edge)
            indptr.append(len(indices))
        return GraphSnapshot(nodes=nodes, order=order, indptr=indptr,
                             indices=indices, edges=edges)

    def close(self) -> None:
        self._driver.close()
