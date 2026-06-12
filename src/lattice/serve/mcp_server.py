"""MCP stdio adapter — exposes a GraphService as Model Context Protocol tools.

Driving adapter: it owns no business logic, only the JSON-RPC/MCP marshalling
around `GraphService`. A minimal, dependency-free stdio implementation of the
MCP `initialize` / `tools/list` / `tools/call` handshake is provided so an IDE
can talk to it with no extra packages. The dispatch is split out as a pure
function (`handle`) so it is unit-testable without real stdio.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from .graph_service import GraphService

PROTOCOL_VERSION = "2024-11-05"

# Tool name -> (json schema, handler(service, args) -> result).
_TOOLS: dict[str, dict[str, Any]] = {
    "graph_stats": {
        "description": "Node/edge counts and a breakdown by kind.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": lambda svc, a: svc.stats(),
    },
    "graph_search": {
        "description": "Find nodes whose label contains a query string.",
        "inputSchema": {"type": "object",
                        "properties": {"query": {"type": "string"},
                                       "limit": {"type": "integer"}},
                        "required": ["query"]},
        "handler": lambda svc, a: svc.search(a["query"], a.get("limit", 20)),
    },
    "graph_neighbors": {
        "description": "Adjacent nodes of a given node id.",
        "inputSchema": {"type": "object",
                        "properties": {"node_id": {"type": "string"}},
                        "required": ["node_id"]},
        "handler": lambda svc, a: svc.neighbors(a["node_id"]),
    },
    "graph_path": {
        "description": "Shortest path (node ids) between two nodes.",
        "inputSchema": {"type": "object",
                        "properties": {"src": {"type": "string"},
                                       "dst": {"type": "string"}},
                        "required": ["src", "dst"]},
        "handler": lambda svc, a: svc.path(a["src"], a["dst"]),
    },
}


def _result(req_id: Any, payload: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": payload}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message}}


def handle(service: GraphService, request: dict) -> dict | None:
    """Process one JSON-RPC request. Returns a response, or None for notifications."""
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "lattice", "version": "0.1.0"},
        })
    if method in ("notifications/initialized", "initialized"):
        return None  # notification, no response
    if method == "tools/list":
        return _result(req_id, {"tools": [
            {"name": name, "description": meta["description"],
             "inputSchema": meta["inputSchema"]}
            for name, meta in _TOOLS.items()
        ]})
    if method == "tools/call":
        name = params.get("name")
        tool = _TOOLS.get(name)
        if tool is None:
            return _error(req_id, -32602, f"unknown tool: {name}")
        try:
            handler: Callable = tool["handler"]
            payload = handler(service, params.get("arguments") or {})
        except KeyError as exc:
            return _error(req_id, -32602, f"missing argument: {exc}")
        return _result(req_id, {
            "content": [{"type": "text",
                         "text": json.dumps(payload, indent=2)}]
        })
    return _error(req_id, -32601, f"method not found: {method}")


def serve(service: GraphService, stdin=None, stdout=None) -> None:
    """Run the stdio loop: one JSON-RPC message per line."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(service, request)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
