"""Measure how much feeding Lattice's graph saves over raw source, in tokens.

The pitch behind a code-knowledge-graph for LLM workflows is that you hand the
model a compact structural map instead of the whole corpus. This module turns
that pitch into a number: it counts the tokens in the raw source, builds the
graph, renders it three ways, and reports the reduction for each.

    python -m lattice.bench.token_impact path/to/project

Token counting uses `tiktoken` when it is installed (accurate, matches the
GPT/Claude family closely enough for a ratio) and a ~4-chars/token heuristic
otherwise — rough, but dependency-free and deterministic so the bundled test
can assert on it in CI.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field

from ..domain.models import GraphSnapshot
from ..ingest.discovery import FileSystemDiscovery
from ..render.context_writer import ContextRenderer
from ..render.json_writer import JsonRenderer

# --- token counting --------------------------------------------------------

try:  # pragma: no cover - exercised only when tiktoken is present
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # noqa: BLE001 - any failure falls back to the heuristic
    _ENC = None


def count_tokens(text: str) -> int:
    """Token count: exact via tiktoken if available, else ~4 chars/token."""
    if not text:
        return 0
    if _ENC is not None:  # pragma: no cover - depends on optional dep
        return len(_ENC.encode(text))
    return (len(text) + 3) // 4


def tokenizer_name() -> str:
    return "tiktoken/cl100k_base" if _ENC is not None else "heuristic(chars/4)"


# --- graph construction ----------------------------------------------------


def build_snapshot(root: str) -> GraphSnapshot:
    """Build a graph for `root` with the deterministic serial pipeline."""
    from ..extract.extractors.python_ast import PythonAstExtractor
    from ..extract.extractors.treesitter import TreeSitterExtractor
    from ..extract.registry import extract_one, register, registered
    from ..graph.csr_store import CsrGraphStore
    from ..pipeline.orchestrator import Pipeline
    from ..pipeline.scheduler import SerialScheduler

    if not registered():  # idempotent if the CLI already registered them
        register(PythonAstExtractor())
        register(TreeSitterExtractor())

    pipeline = Pipeline(
        discovery=FileSystemDiscovery(),
        scheduler=SerialScheduler(),
        store=CsrGraphStore(),
        extract_fn=extract_one,
    )
    return pipeline.run(root)


def corpus_tokens(root: str) -> tuple[int, int]:
    """Raw-source baseline: (total tokens, file count) over the same walk."""
    tokens = files = 0
    for sf in FileSystemDiscovery().walk(root):
        try:
            with open(sf.path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        tokens += count_tokens(text)
        files += 1
    return tokens, files


def _render_to_str(renderer, snapshot: GraphSnapshot) -> str:
    with tempfile.NamedTemporaryFile("r+", suffix=".out", delete=True) as tmp:
        renderer.render(snapshot, tmp.name)
        tmp.seek(0)
        return tmp.read()


# --- the measurement -------------------------------------------------------


@dataclass
class Report:
    root: str
    tokenizer: str
    files: int
    nodes: int
    edges: int
    raw_tokens: int
    # representation name -> token count
    rep_tokens: dict[str, int] = field(default_factory=dict)

    def reduction(self, rep: str) -> float:
        """Fraction of raw-source tokens saved by representation `rep`."""
        if self.raw_tokens == 0:
            return 0.0
        return 1.0 - self.rep_tokens[rep] / self.raw_tokens

    def render_table(self) -> str:
        lines = [
            f"token impact for {self.root}",
            f"  tokenizer : {self.tokenizer}",
            f"  corpus    : {self.files} files, "
            f"{self.nodes} nodes, {self.edges} edges",
            f"  raw source: {self.raw_tokens:>8,} tokens  (baseline)",
            "",
            f"  {'representation':<22}{'tokens':>10}{'vs raw':>10}{'shrink':>9}",
            f"  {'-' * 22}{'-' * 10}{'-' * 10}{'-' * 9}",
        ]
        for rep, toks in self.rep_tokens.items():
            ratio = (self.raw_tokens / toks) if toks else float("inf")
            lines.append(
                f"  {rep:<22}{toks:>10,}{ratio:>9.1f}x"
                f"{self.reduction(rep) * 100:>8.0f}%"
            )
        return "\n".join(lines)


def measure(root: str) -> Report:
    raw_tokens, files = corpus_tokens(root)
    snapshot = build_snapshot(root)

    reps = {
        "graph json (pretty)": _render_to_str(JsonRenderer(indent=2), snapshot),
        "graph json (compact)": _render_to_str(JsonRenderer(indent=None),
                                                snapshot),
        "context pack": _render_to_str(ContextRenderer(), snapshot),
    }
    return Report(
        root=root,
        tokenizer=tokenizer_name(),
        files=files,
        nodes=len(snapshot.nodes),
        edges=len(snapshot.edges),
        raw_tokens=raw_tokens,
        rep_tokens={name: count_tokens(text) for name, text in reps.items()},
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    print(measure(argv[0]).render_table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
