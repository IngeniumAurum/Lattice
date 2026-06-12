"""Live tree-sitter extraction tests — skipped when grammars aren't installed.

Run the full set with: pip install -e ".[treesitter-grammars,dev]"
"""

from __future__ import annotations

import pytest

from lattice.cache.fingerprint import compute_fingerprint
from lattice.domain.models import SourceFile
from lattice.extract.extractors.treesitter import TreeSitterExtractor


def _source(tmp_path, name, language, text):
    p = tmp_path / name
    p.write_text(text)
    return SourceFile(path=str(p), language=language, size=p.stat().st_size,
                      fingerprint=compute_fingerprint(str(p)))


def _require(extractor, file):
    if not extractor.supports(file):
        pytest.skip(f"tree-sitter grammar for {file.language} not installed")


def test_go_extraction(tmp_path):
    ext = TreeSitterExtractor()
    f = _source(tmp_path, "m.go", "go",
                "package main\n"
                "func add(a int) int { return helper(a) }\n"
                "func helper(x int) int { return x }\n")
    _require(ext, f)
    frag = ext.extract(f)
    labels = {n.label for n in frag.nodes}
    assert {"add", "helper"} <= labels
    assert any(e.relation == "calls" and e.target == "helper" for e in frag.edges)


def test_javascript_extraction(tmp_path):
    ext = TreeSitterExtractor()
    f = _source(tmp_path, "m.js", "javascript",
                "class Foo { bar() { return baz(1); } }\n"
                "function baz(n){ return n; }\n")
    _require(ext, f)
    frag = ext.extract(f)
    kinds = {(n.label, n.kind) for n in frag.nodes}
    assert ("Foo", "class") in kinds and ("bar", "method") in kinds
    assert any(e.relation == "calls" and e.target == "baz" for e in frag.edges)
