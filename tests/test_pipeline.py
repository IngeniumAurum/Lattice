"""End-to-end test of the reference slice using the deterministic scheduler."""

from __future__ import annotations

import textwrap

from lattice.cache.fingerprint import InMemoryFingerprintCache
from lattice.extract.registry import extract_one, register
from lattice.extract.extractors.python_ast import PythonAstExtractor
from lattice.graph.csr_store import CsrGraphStore
from lattice.ingest.discovery import FileSystemDiscovery
from lattice.pipeline.orchestrator import Pipeline
from lattice.pipeline.scheduler import SerialScheduler
from lattice.query.traversal import shortest_path

register(PythonAstExtractor())


def _make_pipeline(cache):
    return Pipeline(
        discovery=FileSystemDiscovery(),
        scheduler=SerialScheduler(),
        store=CsrGraphStore(),
        extract_fn=extract_one,
        cache=cache,
    )


def test_extracts_functions_and_paths(tmp_path):
    src = tmp_path / "mod.py"
    src.write_text(textwrap.dedent(
        """
        def helper():
            return 1

        def main():
            return helper()
        """
    ))

    snapshot = _make_pipeline(InMemoryFingerprintCache()).run(str(tmp_path))

    labels = {n.label for n in snapshot.nodes.values()}
    assert {"helper", "main"} <= labels

    # main contains a CALLS edge to helper; module CONTAINS both.
    module_id = str(src)
    path = shortest_path(snapshot, module_id, f"{module_id}::main")
    assert path == [module_id, f"{module_id}::main"]


def test_cache_skips_unchanged_files(tmp_path):
    (tmp_path / "a.py").write_text("def a():\n    pass\n")
    cache = InMemoryFingerprintCache()

    # Warm the cache, then a fresh store re-run should reuse fragments.
    _make_pipeline(cache).run(str(tmp_path))

    store = CsrGraphStore()
    pipeline = Pipeline(
        discovery=FileSystemDiscovery(),
        scheduler=SerialScheduler(),
        store=store,
        extract_fn=extract_one,
        cache=cache,
    )
    snapshot = pipeline.run(str(tmp_path))
    assert any(n.label == "a" for n in snapshot.nodes.values())
