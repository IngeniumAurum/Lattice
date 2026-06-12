# Lattice — Architecture

Lattice turns a folder of source code and documents into a queryable knowledge
graph. It is a ground-up re-architecture of the [graphify](https://github.com/safishamsi/graphify)
concept, designed for **throughput**, **incrementality**, and **extensibility**
under strict SOLID boundaries.

This document explains the design, contrasts it with graphify's, and justifies
each optimization.

---

## 1. What changed, and why

graphify is a **linear, synchronous pipeline** built from flat modules
(`detect.py → extract.py → build.py → cluster.py → analyze.py → report.py →
export.py`). Stages hand each other plain `dict`s and a single mutable
`networkx.Graph`. It works, but it has four structural ceilings:

| # | graphify limitation | Lattice answer |
|---|---------------------|----------------|
| 1 | **Sequential extraction** — files parsed one at a time on a single core. | **Fan-out scheduler** runs CPU-bound parsing across a process pool; I/O-bound enrichment runs on an async pool. |
| 2 | **Whole-corpus reprocessing** — a coarse semantic cache, but a run re-touches everything. | **Per-file fingerprint cache** — only files whose content hash changed are re-extracted. Re-runs are O(changed), not O(repo). |
| 3 | **`networkx.Graph` as the spine** — flexible but memory-heavy and slow to traverse at scale. | **CSR (Compressed Sparse Row) snapshot** for read/query, with a light incremental builder for writes. NetworkX becomes an *optional adapter*, not the core. |
| 4 | **Monolithic `extract.py`** — adding a language or format means editing the hot module. | **Extractor registry** — new extractors register themselves; core never changes (Open/Closed). |

The throughline: graphify couples *policy* (the pipeline) to *mechanism*
(NetworkX, a specific LLM SDK, tree-sitter). Lattice inverts those dependencies
behind ports so mechanism is swappable and parallelizable.

---

## 2. Hexagonal layout (ports & adapters)

```
                         ┌─────────────────────────────┐
                         │        domain (core)        │
                         │  models.py   ports.py       │   ← pure, no I/O, no deps
                         └─────────────┬───────────────┘
                                       │  depends on (interfaces only)
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                               │
  driving side                  pipeline (use cases)            driven side
  cli/app.py  ───────────►  pipeline/orchestrator.py  ◄────────  adapters:
                            pipeline/scheduler.py                 ingest/discovery.py
                                                                  extract/registry.py
                                                                  extract/extractors/*
                                                                  graph/csr_store.py
                                                                  cache/fingerprint.py
                                                                  enrich/llm_port.py
                                                                  render/json_writer.py
```

- **`domain/`** depends on nothing. It defines the data (`Node`, `Edge`,
  `Fragment`, `GraphSnapshot`) and the contracts (`Protocol`s).
- **`pipeline/`** orchestrates the use case purely against those `Protocol`s —
  it never imports a concrete adapter.
- **adapters** implement the ports. Swapping NetworkX for a CSR store, or
  Anthropic for OpenAI, is a one-line wiring change in the composition root
  (`cli/app.py`), touching no business logic. That is **Dependency Inversion**
  in practice.

### File-name mapping vs graphify

Every module is renamed and re-scoped so the two projects never collide and the
responsibilities are sharper:

| graphify | Lattice | Difference |
|----------|---------|------------|
| `detect.py` | `ingest/discovery.py` | gitignore-aware streaming walk, yields lazily |
| `extract.py` | `extract/registry.py` + `extract/extractors/*` | one file per language, registry dispatch |
| `build.py` | `graph/assembler.py` + `graph/csr_store.py` | incremental write model, CSR read model |
| `cluster.py` | `graph/community.py` | operates on CSR snapshot, not live graph |
| `cache.py` | `cache/fingerprint.py` | content-hash keyed, per-file granularity |
| `report.py`/`export.py` | `render/*` | one renderer per format behind a `Renderer` port |
| `serve.py` | `query/traversal.py` (+ future `serve` adapter) | CSR-backed BFS/shortest-path |

---

## 3. The pipeline as a use case

`pipeline/orchestrator.py` reads as a sentence and depends only on ports:

```
discover ──► fingerprint-filter ──► [parallel extract] ──► assemble ──► snapshot
                  │                         │
              cache hit?                cache miss
              reuse Fragment           extract + cache.put
```

1. **Discover** (`SourceDiscovery`): stream `SourceFile`s, honoring ignore
   rules. Lazy — never materializes the full file list.
2. **Fingerprint filter** (`FingerprintCache`): for each file, compute a fast
   content hash. Cache hit → reuse the stored `Fragment`, skip all work.
3. **Parallel extract** (`Scheduler` + `Extractor`): only cache-miss files reach
   the process pool. Each worker picks the first registered extractor that
   `supports()` the file and returns a `Fragment` (nodes + edges for that file).
4. **Assemble** (`GraphStore`): fragments stream into the incremental store.
   Because a fragment is *self-contained per file*, assembly is associative —
   order-independent and trivially mergeable.
5. **Snapshot** (`GraphSnapshot`): freeze into a CSR structure for querying,
   clustering, and rendering.

The unit of work is the **`Fragment`** — one file's contribution. This single
decision is what unlocks parallelism (fragments are independent), incrementality
(fragments are cacheable by file hash), and mergeability (fragments compose).

---

## 4. Performance design

### 4.1 Parallel fan-out (`pipeline/scheduler.py`)
CPU-bound AST parsing is embarrassingly parallel once work is per-file. The
`Scheduler` port abstracts execution so the same orchestrator runs:
- `ProcessPoolScheduler` — default, scales with cores;
- `SerialScheduler` — deterministic, for tests/CI debugging;
- (future) `AsyncScheduler` — for I/O-bound enrichment.

Liskov holds: any scheduler is substitutable; the orchestrator can't tell which
it got.

### 4.2 Incremental cache (`cache/fingerprint.py`)
Key = `blake2b(content) + size + mtime`. On a warm repo where 1% of files
changed, ~99% of extraction is skipped. graphify's run cost scales with repo
size; Lattice's scales with the diff.

### 4.3 CSR graph store (`graph/csr_store.py`)
Writes accumulate in a compact adjacency map. `snapshot()` compiles to three
flat arrays (`indptr`, `indices`, `edge_data`) — the CSR format. Neighbor
lookups are a contiguous array slice (cache-friendly, allocation-free), versus
NetworkX's nested-dict hop per edge. BFS/shortest-path in `query/traversal.py`
runs directly on these arrays.

### 4.4 Streaming, not buffering
Discovery yields, extraction streams fragments, assembly consumes them as they
land. Peak memory is bounded by `pool_size` in-flight fragments, not the whole
corpus.

---

## 5. SOLID, concretely

- **S — Single Responsibility:** each module owns one verb. `discovery.py` only
  walks; `csr_store.py` only stores; extractors only parse. graphify's
  `export.py` (Obsidian + JSON + HTML + SVG) is split into one renderer each.
- **O — Open/Closed:** add a language by dropping a file in
  `extract/extractors/` and calling `register()`. Core orchestration is never
  edited. New output format = new `Renderer`, registered the same way.
- **L — Liskov:** every scheduler, store, and extractor honors its `Protocol`
  exactly, so the composition root mixes and matches freely.
- **I — Interface Segregation:** ports are narrow. An `Extractor` knows nothing
  about graphs; a `Renderer` knows nothing about caching. No fat "do
  everything" interface.
- **D — Dependency Inversion:** `pipeline/` imports `domain.ports` only. All
  concretes are injected at `cli/app.py`. The arrows point inward.

---

## 6. Extending Lattice

- **New language:** implement `Extractor` in `extract/extractors/<lang>.py`,
  `register()` it. Tree-sitter, regex, or native AST behind the same port.
- **New LLM provider:** implement `Enricher` (`enrich/llm_port.py` defines the
  contract). The pipeline is provider-agnostic.
- **New storage:** implement `GraphStore` — e.g. a Neo4j or DuckDB adapter —
  without touching extraction or rendering.
- **New output:** implement `Renderer` (`render/json_writer.py` is the
  reference).

---

## 7. What runs today

The contracts are real, not aspirational — a full slice is implemented:

- **Extraction:** `extract/extractors/python_ast.py` (pure stdlib) plus
  `extract/extractors/treesitter.py` — one config-driven adapter covering
  JS/TS, Go, Rust, and Java via tree-sitter. The tree-sitter adapter lazily
  loads its grammars and reports `supports() == False` when the optional extra
  is absent, so the pipeline degrades gracefully to other extractors.
- **Clustering:** `graph/community.py` — a single-level Louvain local-move pass
  over the CSR snapshot. Chosen over naive label propagation, which collapses
  weakly-connected clusters across a single bridge edge; Louvain maximizes
  modularity gain and keeps them separate. Deterministic, dependency-free.
- **Rendering:** three `Renderer` adapters — `render/json_writer.py`,
  `render/mermaid_writer.py` (clustered `flowchart`, capped by node degree), and
  `render/html_writer.py` (self-contained offline force-directed canvas viz with
  search, confidence filter, and community coloring).
- **Querying:** `query/traversal.py` — BFS shortest path over the CSR arrays.

- **Serving:** `serve/graph_service.py` is a pure query use case (search,
  neighbors, shortest-path, stats); `serve/mcp_server.py` is a thin driving
  adapter exposing it over MCP stdio JSON-RPC (`initialize` / `tools/list` /
  `tools/call`), with no SDK dependency. The split keeps protocol marshalling
  out of the query logic.

All wired in `cli/app.py`:
`python -m lattice <path> -f json html mermaid --communities --serve`.

### Optional adapters demonstrating the ports

These ship as drop-in substitutes, selected at the composition root, proving the
seams hold:

- `graph/leiden.py` — same `detect()` contract as Louvain, backed by
  `igraph`/`leidenalg` (`--leiden`, falls back to Louvain when absent).
- `graph/neo4j_store.py` — a `GraphStore` that persists to Neo4j via batched
  `UNWIND`/`MERGE` and rehydrates a CSR snapshot, swappable for `CsrGraphStore`
  with no change to extraction, querying, or rendering.

A CI workflow (`.github/workflows/ci.yml`) installs the offline grammars and
runs the suite — including **live** tree-sitter extraction on Go/JS fixtures —
across Python 3.10–3.12, plus an end-to-end CLI smoke test.
