"""Composition root + CLI.

This is the ONLY place concrete adapters are named and wired together. Swapping
an implementation (serial vs pool scheduler, CSR vs Neo4j store, JSON vs HTML
renderer) is a change here and nowhere else.
"""

from __future__ import annotations

import argparse
import sys

from ..cache.fingerprint import InMemoryFingerprintCache
from ..enrich.llm_port import NullEnricher
from ..extract.registry import extract_one, register
from ..extract.extractors.python_ast import PythonAstExtractor
from ..graph.csr_store import CsrGraphStore
from ..ingest.discovery import FileSystemDiscovery
from ..pipeline.orchestrator import Pipeline
from ..pipeline.scheduler import ProcessPoolScheduler, SerialScheduler
from ..render.json_writer import JsonRenderer

# Register extractors (Open/Closed: extend by adding lines here, not editing core).
register(PythonAstExtractor())


def build_pipeline(serial: bool) -> Pipeline:
    scheduler = SerialScheduler() if serial else ProcessPoolScheduler()
    return Pipeline(
        discovery=FileSystemDiscovery(),
        scheduler=scheduler,
        store=CsrGraphStore(),
        extract_fn=extract_one,
        cache=InMemoryFingerprintCache(),
        enricher=NullEnricher(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lattice",
                                     description="Build a code knowledge graph.")
    parser.add_argument("root", help="directory to analyze")
    parser.add_argument("-o", "--out", default="lattice.graph.json",
                        help="output JSON path")
    parser.add_argument("--serial", action="store_true",
                        help="disable the process pool (deterministic)")
    args = parser.parse_args(argv)

    pipeline = build_pipeline(serial=args.serial)
    snapshot = pipeline.run(args.root)
    out = JsonRenderer().render(snapshot, args.out)

    print(f"nodes={len(snapshot.nodes)} edges={len(snapshot.edges)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
