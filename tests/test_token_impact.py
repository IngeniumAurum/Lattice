"""Guards the token-efficiency contract: the context pack must beat raw source.

These run in CI so a regression that bloats the LLM-facing representation (e.g.
someone makes the context renderer verbose, or wires JSON as the default context
format) fails the build instead of silently costing tokens in production.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lattice.bench import token_impact
from lattice.bench.token_impact import Tokenizer
from lattice.domain.models import Edge, Fragment, Node
from lattice.graph.csr_store import CsrGraphStore
from lattice.render.context_writer import ContextRenderer
from lattice.render.json_writer import JsonRenderer

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _byte_tokenizer() -> Tokenizer:
    """A real `tiktoken` encoder built in-memory (no network): one token/byte.

    Lets the exact path be tested deterministically and offline, instead of
    depending on a downloadable vocabulary.
    """
    tiktoken = pytest.importorskip("tiktoken")
    enc = tiktoken.Encoding(
        name="bytes-test",
        pat_str=r".",
        mergeable_ranks={bytes([i]): i for i in range(256)},
        special_tokens={},
    )
    return Tokenizer(name="tiktoken/bytes-test", exact=True, encode=enc.encode)


def test_count_tokens_is_sane():
    assert token_impact.count_tokens("") == 0
    assert token_impact.count_tokens("a") >= 1
    # Monotonic in length under the heuristic; tiktoken keeps this true too.
    assert token_impact.count_tokens("x" * 400) > token_impact.count_tokens("x")


def test_heuristic_is_marked_not_exact():
    tok = Tokenizer(name="heuristic(chars/4)", exact=False)
    assert tok.exact is False
    assert tok.count("") == 0
    assert tok.count("abcd") == 1  # 4 chars -> 1 token under the heuristic


def test_exact_tokenizer_counts_via_real_bpe():
    tok = _byte_tokenizer()
    assert tok.exact is True
    # Byte-level encoder: ASCII token count equals character count, exactly.
    assert tok.count("hello") == 5
    assert tok.count("") == 0


def test_require_exact_fails_loudly_when_vocab_unavailable():
    # A vanishingly unlikely encoding name can never load, so --exact must raise
    # with an install hint rather than silently returning the heuristic.
    with pytest.raises(RuntimeError, match="--exact"):
        token_impact.get_tokenizer("no_such_encoding_xyz", require_exact=True)
    # Without require_exact the same failure degrades to the labelled heuristic.
    fallback = token_impact.get_tokenizer("no_such_encoding_xyz")
    assert fallback.exact is False


def test_measure_reports_exactness_flag():
    report = token_impact.measure(SRC, tokenizer=_byte_tokenizer())
    assert report.exact is True
    assert "ESTIMATE" not in report.render_table()
    # Same structural win must hold under an exact tokenizer, not just chars/4.
    assert report.reduction("context pack") > 0.5


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
