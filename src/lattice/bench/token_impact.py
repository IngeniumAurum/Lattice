"""Measure how much feeding Lattice's graph saves over raw source, in tokens.

The pitch behind a code-knowledge-graph for LLM workflows is that you hand the
model a compact structural map instead of the whole corpus. This module turns
that pitch into a number: it counts the tokens in the raw source, builds the
graph, renders it three ways, and reports the reduction for each.

    python -m lattice.bench.token_impact path/to/project          # exact if available
    python -m lattice.bench.token_impact path/to/project --exact  # exact or fail loudly

Token counting uses a real BPE tokenizer (`tiktoken`) when its vocabulary is
available, so the reported ratio is *measured*, not estimated. When tiktoken is
absent — or its encoding cannot be loaded (e.g. an offline machine that has
never cached the vocab) — it falls back to a ~4-chars/token heuristic, and every
surface clearly labels the result as an estimate. Pass ``--exact`` to forbid the
fallback: the run then fails with an install hint instead of quietly reporting
approximate numbers as if they were measured.

Install the exact path with ``pip install -e '.[bench]'``.
"""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field

from ..domain.models import GraphSnapshot
from ..ingest.discovery import FileSystemDiscovery
from ..render.context_writer import ContextRenderer
from ..render.json_writer import JsonRenderer

# --- token counting --------------------------------------------------------

# Modern GPT-4o / 4.1 tokenizer; a good proxy for the Claude family for a ratio.
DEFAULT_ENCODING = "o200k_base"


@dataclass(frozen=True)
class Tokenizer:
    """A token counter and how trustworthy it is.

    ``exact`` is True only when a real BPE tokenizer backs ``encode``; the
    heuristic fallback sets it False so callers can refuse to present estimates
    as measurements.
    """

    name: str
    exact: bool
    encode: Callable[[str], list] | None = None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self.encode is not None:
            return len(self.encode(text))
        return (len(text) + 3) // 4


_HEURISTIC = Tokenizer(name="heuristic(chars/4)", exact=False, encode=None)


def get_tokenizer(encoding: str = DEFAULT_ENCODING,
                  *, require_exact: bool = False) -> Tokenizer:
    """Return the best available tokenizer.

    Tries to load `tiktoken`'s `encoding`. Falls back to the chars/4 heuristic
    unless `require_exact`, in which case the failure is raised with an install
    hint rather than silently downgraded.
    """
    try:
        import tiktoken

        enc = tiktoken.get_encoding(encoding)
        return Tokenizer(name=f"tiktoken/{encoding}", exact=True, encode=enc.encode)
    except Exception as exc:  # noqa: BLE001 - import error or vocab-load failure
        if require_exact:
            raise RuntimeError(
                f"--exact requested but the tiktoken encoding {encoding!r} could "
                "not be loaded "
                f"({type(exc).__name__}: {exc}). Install the exact path with "
                "`pip install -e '.[bench]'` on a machine that can reach (or has "
                "cached) the tiktoken vocabulary."
            ) from exc
        return _HEURISTIC


# Lazily-resolved default so importing this module never hits the network.
_DEFAULT: Tokenizer | None = None


def _default_tokenizer() -> Tokenizer:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = get_tokenizer()
    return _DEFAULT


def count_tokens(text: str, tokenizer: Tokenizer | None = None) -> int:
    """Token count via `tokenizer`, or the lazily-resolved default."""
    return (tokenizer or _default_tokenizer()).count(text)


def tokenizer_name() -> str:
    return _default_tokenizer().name


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


def corpus_tokens(root: str, tokenizer: Tokenizer | None = None) -> tuple[int, int]:
    """Raw-source baseline: (total tokens, file count) over the same walk."""
    tok = tokenizer or _default_tokenizer()
    tokens = files = 0
    for sf in FileSystemDiscovery().walk(root):
        try:
            with open(sf.path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        tokens += tok.count(text)
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
    exact: bool
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
        label = self.tokenizer if self.exact else f"{self.tokenizer} — ESTIMATE"
        lines = [
            f"token impact for {self.root}",
            f"  tokenizer : {label}",
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
        if not self.exact:
            lines += [
                "",
                "  note: counts are a chars/4 estimate. Install `.[bench]` (tiktoken)"
                " or pass --exact for measured token counts.",
            ]
        return "\n".join(lines)


def measure(root: str, *, encoding: str = DEFAULT_ENCODING,
            require_exact: bool = False,
            tokenizer: Tokenizer | None = None) -> Report:
    tok = tokenizer or get_tokenizer(encoding, require_exact=require_exact)
    raw_tokens, files = corpus_tokens(root, tok)
    snapshot = build_snapshot(root)

    reps = {
        "graph json (pretty)": _render_to_str(JsonRenderer(indent=2), snapshot),
        "graph json (compact)": _render_to_str(JsonRenderer(indent=None),
                                                snapshot),
        "context pack": _render_to_str(ContextRenderer(), snapshot),
    }
    return Report(
        root=root,
        tokenizer=tok.name,
        exact=tok.exact,
        files=files,
        nodes=len(snapshot.nodes),
        edges=len(snapshot.edges),
        raw_tokens=raw_tokens,
        rep_tokens={name: tok.count(text) for name, text in reps.items()},
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0

    root = argv[0]
    rest = argv[1:]
    require_exact = "--exact" in rest
    encoding = DEFAULT_ENCODING
    if "--tokenizer" in rest:
        i = rest.index("--tokenizer")
        try:
            encoding = rest[i + 1]
        except IndexError:
            print("error: --tokenizer needs an encoding name "
                  "(e.g. o200k_base, cl100k_base)", file=sys.stderr)
            return 2

    try:
        report = measure(root, encoding=encoding, require_exact=require_exact)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(report.render_table())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
