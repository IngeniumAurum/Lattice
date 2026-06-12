"""Round-trip test for Neo4jGraphStore — skipped unless a Neo4j server is set.

Bring one up with `docker compose -f docker-compose.neo4j.yml up -d`, then run
with NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD in the environment. CI provides
these via a service container (see .github/workflows/ci.yml).
"""

from __future__ import annotations

import os
import uuid

import pytest

from lattice.domain.models import Confidence, Edge, Fragment, Node

NEO4J_URI = os.environ.get("NEO4J_URI")

pytestmark = pytest.mark.skipif(
    not NEO4J_URI, reason="set NEO4J_URI to run the Neo4j integration test")


@pytest.fixture
def store():
    pytest.importorskip("neo4j")
    from lattice.graph.neo4j_store import Neo4jGraphStore

    db = "neo4j"
    s = Neo4jGraphStore(
        uri=NEO4J_URI,
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "latticetest"),
        database=db,
    )
    # Isolate this run so repeated CI runs don't accumulate nodes.
    with s._driver.session(database=db) as session:
        session.run("MATCH (n:Symbol) DETACH DELETE n")
    yield s
    s.close()


def test_neo4j_round_trip(store):
    tag = uuid.uuid4().hex[:8]
    a, b = f"{tag}:a", f"{tag}:b"
    fragment = Fragment(
        path="f", fingerprint="x",
        nodes=[Node(id=a, label="a", kind="function", path="f", line=1),
               Node(id=b, label="b", kind="function", path="f", line=2)],
        edges=[Edge(a, b, "calls", confidence=Confidence.INFERRED, weight=2.0)],
    )
    store.add(fragment)

    snapshot = store.snapshot()
    assert {n.label for n in snapshot.nodes.values()} >= {"a", "b"}
    assert snapshot.neighbors(a) == [b]
    edge = next(e for e in snapshot.edges if e.source == a and e.target == b)
    assert edge.relation == "calls"
    assert edge.confidence is Confidence.INFERRED
    assert edge.weight == 2.0
