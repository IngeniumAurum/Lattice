"""Composition root + CLI.

This is the ONLY place concrete adapters are named and wired together. Swapping
an implementation (serial vs pool scheduler, CSR vs Neo4j store, JSON vs HTML
renderer) is a change here and nowhere else.
"""

from __future__ import annotations

import argparse
import os
import sys

from ..cache.fingerprint import InMemoryFingerprintCache
from ..cache.sqlite_cache import SqliteFingerprintCache
from ..enrich.anthropic_enricher import AnthropicEnricher
from ..enrich.llm_port import NullEnricher
from ..extract.registry import extract_one, register
from ..extract.extractors.python_ast import PythonAstExtractor
from ..extract.extractors.treesitter import TreeSitterExtractor
from ..graph import community, leiden
from ..graph.csr_store import CsrGraphStore
from ..ingest.discovery import FileSystemDiscovery
from ..pipeline.orchestrator import Pipeline
from ..pipeline.scheduler import ProcessPoolScheduler, SerialScheduler
from ..render.html_writer import HtmlRenderer
from ..render.json_writer import JsonRenderer
from ..render.mermaid_writer import MermaidRenderer
from ..serve.graph_service import GraphService
from ..serve.mcp_server import serve as mcp_serve

# Register extractors (Open/Closed: extend by adding lines here, not editing core).
# Order = priority: the native Python AST is preferred; tree-sitter covers the
# rest, and quietly no-ops if its grammars aren't installed.
register(PythonAstExtractor())
register(TreeSitterExtractor())

# Renderer registry — one adapter per format, all behind the Renderer port.
_RENDERERS = {
    "json": (JsonRenderer, ".graph.json"),
    "html": (HtmlRenderer, ".graph.html"),
    "mermaid": (MermaidRenderer, ".graph.mmd"),
}


def build_pipeline(serial: bool, cache_db: str | None,
                   enrich: bool, status) -> Pipeline:
    scheduler = SerialScheduler() if serial else ProcessPoolScheduler()
    cache = (SqliteFingerprintCache(cache_db) if cache_db
             else InMemoryFingerprintCache())

    enricher = NullEnricher()
    if enrich:
        anthropic = AnthropicEnricher()
        if anthropic.available():
            enricher = anthropic
        else:
            print("warning: --enrich requested but the anthropic SDK / API key "
                  "is unavailable; continuing without enrichment", file=status)

    return Pipeline(
        discovery=FileSystemDiscovery(),
        scheduler=scheduler,
        store=CsrGraphStore(),
        extract_fn=extract_one,
        cache=cache,
        enricher=enricher,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lattice",
                                     description="Build a code knowledge graph.")
    parser.add_argument("root", help="directory to analyze")
    parser.add_argument("-o", "--out", default="lattice",
                        help="output path prefix (extension added per format)")
    parser.add_argument("-f", "--format", default=["json"], nargs="+",
                        choices=sorted(_RENDERERS), help="output format(s)")
    parser.add_argument("--communities", action="store_true",
                        help="run community detection and annotate nodes")
    parser.add_argument("--leiden", action="store_true",
                        help="prefer the Leiden algorithm (falls back to Louvain)")
    parser.add_argument("--serve", action="store_true",
                        help="after building, expose the graph as an MCP stdio server")
    parser.add_argument("--cache-db", metavar="PATH",
                        help="persist the incremental cache to a SQLite file")
    parser.add_argument("--enrich", action="store_true",
                        help="add LLM summaries to modules (needs the anthropic extra)")
    parser.add_argument("--serial", action="store_true",
                        help="disable the process pool (deterministic)")
    args = parser.parse_args(argv)

    # In --serve mode stdout must carry only JSON-RPC, so status goes to stderr.
    status = sys.stderr if args.serve else sys.stdout

    pipeline = build_pipeline(serial=args.serial, cache_db=args.cache_db,
                              enrich=args.enrich, status=status)
    snapshot = pipeline.run(args.root)

    if args.communities:
        if args.leiden and leiden.available():
            communities = leiden.detect(snapshot)
            algo = "leiden"
        else:
            communities = community.detect(snapshot)
            algo = "louvain"
        snapshot = community.annotate(snapshot, communities)
        print(f"communities={len(set(communities.values()))} ({algo})",
              file=status)

    outputs = []
    for fmt in args.format:
        renderer_cls, suffix = _RENDERERS[fmt]
        out_path = f"{args.out}{suffix}" if not os.path.splitext(args.out)[1] \
            else args.out
        outputs.append(renderer_cls().render(snapshot, out_path))

    print(f"nodes={len(snapshot.nodes)} edges={len(snapshot.edges)} -> "
          f"{', '.join(outputs)}", file=status)

    if args.serve:
        print("lattice MCP server ready on stdio", file=sys.stderr)
        mcp_serve(GraphService(snapshot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
