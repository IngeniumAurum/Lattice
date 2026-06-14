"""Guards the token-efficiency contract: the context pack must beat raw source.

These run in CI so a regression that bloats the LLM-facing representation (e.g.
someone makes the context renderer verbose, or wires JSON as the default context
format) fails the build instead of silently costing tokens in production.
"""

from __future__ import annotations

from pathlib import Path

from lattice.bench import token_impact
from lattice.domain.models import Edge, Fragment, Node
from lattice.graph.csr_store import CsrGraphStore
from lattice.render.context_writer import ContextRenderer
from lattice.render.json_writer import JsonRenderer

SRC = str(Path(__file__).resolve().parents[1] / "src")


def test_count_tokens_is_sane():
    assert token_impact.count_tokens("") == 0
    assert token_impact.count_tokens("a") >= 1
    # Monotonic in length under the heuristic; tiktoken keeps this true too.
    assert token_impact.count_tokens("x" * 400) > token_impact.count_tokens("x")


def test_context_pack_beats_raw_source_on_the_package():
    report = token_impact.measure(SRC)
    assert report.nodes > 0 and report.edges > 0

    # The whole point: the LLM-facing map is dramatically smaller than dumping
    # the corpus. Keep the bar well below the measured ~5x so the test is stable.
    assert report.reduction("context pack") > 0.5
    assert report.rep_tokens["context pack"] < report.raw_tokens

    # And the context pack must beat the JSON renderers it competes with.
    assert (report.rep_tokens["context pack"]
            < report.rep_tokens["graph json (compact)"])
    assert (report.rep_tokens["graph json (compact)"]
            <= report.rep_tokens["graph json (pretty)"])


def _two_node_snapshot():
    store = CsrGraphStore()
    store.add(Fragment(
        path="m.py", fingerprint="x",
        nodes=[
            Node(id="m.py", label="m.py", kind="module", path="m.py"),
            Node(id="m.py::f", label="f", kind="function", path="m.py", line=3),
        ],
        edges=[
            Edge("m.py", "m.py::f", "contains"),
            Edge("m.py::f", "helper", "calls"),
        ],
    ))
    return store.snapshot()


def test_context_renderer_writes_smaller_file_than_json(tmp_path):
    snap = _two_node_snapshot()

    cpath = ContextRenderer().render(snap, str(tmp_path / "g.txt"))
    jpath = JsonRenderer().render(snap, str(tmp_path / "g.json"))
    ctext = Path(cpath).read_text()
    jtext = Path(jpath).read_text()

    assert len(ctext) < len(jtext)
    # The compact map still carries the structural facts a model needs.
    assert "@m.py" in ctext
    assert "fn f L3" in ctext
    assert "calls helper" in ctext
