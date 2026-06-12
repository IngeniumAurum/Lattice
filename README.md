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
python -m lattice path/to/project -o graph.json

# deterministic single-process mode (handy in CI)
python -m lattice path/to/project --serial
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
  render/        # json_writer.py  — one renderer per output format
  cli/           # app.py          — composition root (wires adapters)
```

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
