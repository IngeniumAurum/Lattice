"""Renderer adapter — a compact textual "context pack" for LLM consumption.

The JSON and HTML renderers target machines and humans; this one targets a
*language model's context window*. It strips everything a model does not need
in order to reason about structure — indentation, repeated keys, quoting, the
confidence/weight fields — and emits a dense, line-oriented code map: symbols
grouped by file, each followed by its outgoing relations. The result is a small
fraction of the raw corpus's token count, which is the whole point of handing a
model a graph instead of the source.

Same `render()` contract as the other renderers — Open/Closed for outputs.
"""

from __future__ import annotations

from collections import defaultdict

from ..domain.models import GraphSnapshot

# Short kind tags keep the leftmost column cheap (one token instead of two).
_KIND_ABBR = {"module": "mod", "function": "fn", "class": "cls",
              "external": "ext"}


class ContextRenderer:
    """Token-lean text renderer behind the same Renderer port as the rest."""

    def __init__(self, include_external: bool = False,
                 max_targets: int = 12) -> None:
        # External call/import targets balloon the map without adding structure;
        # off by default for the leanest output. max_targets caps fan-out so a
        # single hot function can't dominate the budget.
        self._include_external = include_external
        self._max_targets = max_targets

    def render(self, snapshot: GraphSnapshot, out_path: str) -> str:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(self.to_text(snapshot))
        return out_path

    def to_text(self, snapshot: GraphSnapshot) -> str:
        # Outgoing edges per source id, grouped by relation (order-preserving).
        out: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list))
        for e in snapshot.edges:
            tgt = snapshot.nodes.get(e.target)
            out[e.source][e.relation].append(tgt.label if tgt else e.target)

        by_path: dict[str, list] = defaultdict(list)
        for node in snapshot.nodes.values():
            if node.kind == "external" and not self._include_external:
                continue
            by_path[node.path or "<external>"].append(node)

        lines = [f"{len(snapshot.nodes)} nodes {len(snapshot.edges)} edges "
                 f"{len(by_path)} files"]
        for path in sorted(by_path):
            lines.append(f"@{path}")
            for node in sorted(by_path[path], key=lambda n: (n.line, n.label)):
                abbr = _KIND_ABBR.get(node.kind, node.kind)
                rels = []
                for relation, targets in out.get(node.id, {}).items():
                    seen = list(dict.fromkeys(targets))[: self._max_targets]
                    rels.append(f"{relation} " + ",".join(seen))
                loc = f" L{node.line}" if node.line else ""
                tail = ("  " + "; ".join(rels)) if rels else ""
                lines.append(f"  {abbr} {node.label}{loc}{tail}")
        return "\n".join(lines) + "\n"
