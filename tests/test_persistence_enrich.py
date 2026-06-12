"""Tests for the SQLite persistent cache and the Anthropic enricher (faked)."""

from __future__ import annotations

from lattice.cache.sqlite_cache import SqliteFingerprintCache
from lattice.domain.models import Confidence, Edge, Fragment, Node, SourceFile
from lattice.enrich.anthropic_enricher import AnthropicEnricher


def _fragment(fp="fp1"):
    return Fragment(
        path="m.py", fingerprint=fp,
        nodes=[Node(id="m.py", label="m.py", kind="module", path="m.py"),
               Node(id="m.py::run", label="run", kind="function", path="m.py")],
        edges=[Edge("m.py", "m.py::run", "contains",
                    confidence=Confidence.EXTRACTED)],
    )


def test_sqlite_cache_round_trip_and_invalidation(tmp_path):
    db = str(tmp_path / "c.db")
    cache = SqliteFingerprintCache(db)
    cache.put(_fragment("fp1"))
    cache.close()

    # Reopen: a cold process still hits the persisted fragment.
    reopened = SqliteFingerprintCache(db)
    hit = reopened.get(SourceFile("m.py", "python", 10, "fp1"))
    assert hit is not None
    assert {n.label for n in hit.nodes} == {"m.py", "run"}
    assert hit.edges[0].confidence is Confidence.EXTRACTED

    # A changed fingerprint must miss.
    assert reopened.get(SourceFile("m.py", "python", 10, "fp2")) is None
    reopened.close()


class _FakeBlock:
    type = "text"
    text = '{"summary": "Runs the thing."}'


class _FakeResponse:
    stop_reason = "end_turn"
    content = [_FakeBlock()]


class _FakeClient:
    def __init__(self):
        self.calls = []

    class _Messages:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            self._outer.calls.append(kwargs)
            return _FakeResponse()

    @property
    def messages(self):
        return _FakeClient._Messages(self)


def test_enricher_adds_summaries_with_injected_client():
    client = _FakeClient()
    enricher = AnthropicEnricher(client=client)
    assert enricher.available()

    enriched = list(enricher.enrich([_fragment()]))
    module = next(n for n in enriched[0].nodes if n.kind == "module")
    assert module.meta["summary"] == "Runs the thing."
    # Symbols were sent; module path included in the prompt.
    assert "run" in client.calls[0]["messages"][0]["content"]


def test_enricher_without_client_is_identity():
    enricher = AnthropicEnricher(client=None)
    enricher._client = None  # force the unavailable path
    frags = [_fragment()]
    assert list(enricher.enrich(frags)) == frags
