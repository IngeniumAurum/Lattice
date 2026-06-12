"""Tests for the GraphService use case and the MCP JSON-RPC dispatch."""

from __future__ import annotations

import json

from lattice.domain.models import Edge, Fragment, Node
from lattice.graph.csr_store import CsrGraphStore
from lattice.serve.graph_service import GraphService
from lattice.serve.mcp_server import handle


def _service():
    store = CsrGraphStore()
    nodes = [Node(id=x, label=x, kind="function", path="f") for x in "ABC"]
    edges = [Edge("A", "B", "calls"), Edge("B", "C", "calls")]
    store.add(Fragment(path="f", fingerprint="x", nodes=nodes, edges=edges))
    return GraphService(store.snapshot())


def test_service_queries():
    svc = _service()
    assert svc.stats()["nodes"] == 3
    assert {h["id"] for h in svc.search("A")} == {"A"}
    assert [n["id"] for n in svc.neighbors("B")] == ["C"]
    assert svc.path("A", "C") == ["A", "B", "C"]


def test_mcp_initialize_and_list():
    svc = _service()
    init = handle(svc, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init["result"]["serverInfo"]["name"] == "lattice"

    listed = handle(svc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in listed["result"]["tools"]}
    assert {"graph_stats", "graph_search", "graph_neighbors", "graph_path"} == names


def test_mcp_tool_call_and_errors():
    svc = _service()
    resp = handle(svc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "graph_path",
                                   "arguments": {"src": "A", "dst": "C"}}})
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload == ["A", "B", "C"]

    unknown = handle(svc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                           "params": {"name": "nope", "arguments": {}}})
    assert unknown["error"]["code"] == -32602

    # initialized notification gets no response
    assert handle(svc, {"jsonrpc": "2.0",
                        "method": "notifications/initialized"}) is None
