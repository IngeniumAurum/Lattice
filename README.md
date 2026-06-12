# Lattice

An optimized, incremental **code-to-knowledge-graph** engine — a ground-up
re-architecture of the [graphify](https://github.com/safishamsi/graphify)
concept built for throughput and extensibility.

Point it at a folder; it parses the source, builds a typed node-and-edge graph,
and exports it for querying and visualization.

## Why it's different

| | graphify | Lattice |
|---|---|---|
| Pipeline | linear, single-core | **parallel fan-out** across a process pool |
| Re-runs | reprocess corpus | **per-file fingerprint cache** — cost scales with the diff |
| Graph spine | `networkx.Graph` | **CSR snapshot** for cache-friendly traversal |
| New language | edit `extract.py` | **register an extractor** — core untouched |
| LLM / storage | wired in | **ports & adapters** — swap at the composition root |

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full design and the SOLID
rationale.

## Quick start

```bash
# zero runtime dependencies — the reference path is pure stdlib
python -m lattice path/to/project -o graph

# multiple formats + community detection in one pass
python -m lattice path/to/project -f json html mermaid --communities -o graph

# deterministic single-process mode (handy in CI)
python -m lattice path/to/project --serial
```

Outputs (by `-f`): `json` (full graph), `html` (self-contained interactive
viz — search, filter, community colors, offline), `mermaid` (architecture
diagram, clustered by community). `--communities` runs Louvain local-move
clustering and annotates every node.

Multi-language parsing (JS/TS, Go, Rust, Java) activates automatically when the
tree-sitter grammars are installed; without them, the pure-stdlib Python
extractor still works and other languages are skipped:

```bash
pip install -e ".[treesitter-grammars]"   # bundled, offline grammars (used in CI)
# or: pip install -e ".[treesitter]"       # language-pack (fetches grammars on demand)
```

### Optional adapters (same ports, swap at the composition root)

```bash
# Higher-quality clustering via Leiden (falls back to Louvain if absent)
pip install -e ".[leiden]"
python -m lattice path/to/project --communities --leiden

# Serve the graph to an IDE over MCP (stdio JSON-RPC; clean stdout)
python -m lattice path/to/project --serve
#   tools: graph_stats · graph_search · graph_neighbors · graph_path

# Persistent incremental cache — re-runs only re-parse changed files, across
# invocations (cost scales with the diff even on a cold process)
python -m lattice path/to/project --cache-db .lattice.cache.db

# LLM summaries on module nodes (provider-agnostic Enricher port; Anthropic)
pip install -e ".[anthropic]"   # needs ANTHROPIC_API_KEY
python -m lattice path/to/project --enrich

# Persist to Neo4j instead of the in-memory CSR store
pip install -e ".[neo4j]"
docker compose -f docker-compose.neo4j.yml up -d   # then wire Neo4jGraphStore
```

## Layout

```
src/lattice/
  domain/        # entities + ports (no I/O, no deps) — the stable core
  ingest/        # discovery.py    — lazy, ignore-aware file walk
  cache/         # fingerprint.py  — per-file incremental cache
  extract/       # registry.py + extractors/ — pluggable parsers
  pipeline/      # orchestrator.py + scheduler.py — the use case + execution
  graph/         # csr_store.py    — incremental write, CSR read
  query/         # traversal.py    — BFS / shortest path over CSR
  enrich/        # llm_port.py     — provider-agnostic semantic pass
  render/        # json/html/mermaid_writer.py — one renderer per format
  serve/         # graph_service.py + mcp_server.py — MCP stdio adapter
  cli/           # app.py          — composition root (wires adapters)
```

Optional adapters behind the same ports: `graph/leiden.py` (clustering),
`graph/neo4j_store.py` (`GraphStore`), `extract/extractors/treesitter.py`
(multi-language).

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Extending

- **Language:** add `extract/extractors/<lang>.py` implementing `Extractor`, then
  `register()` it in `cli/app.py`.
- **Output format / storage / LLM:** implement the matching port
  (`Renderer` / `GraphStore` / `Enricher`) and wire it in the composition root.

MIT licensed.
