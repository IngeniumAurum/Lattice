"""LLM Enricher adapter — semantic summaries via the Anthropic API.

Implements the same `Enricher` port as `NullEnricher`, so it drops into the
pipeline at the composition root without touching extraction or graph code. For
each module fragment it asks Claude for a one-line summary derived from the
module's symbol names (no file contents are sent), and writes it to the module
node's `meta['summary']`.

Design notes:
- **Provider stays behind the port.** The pipeline never imports this module
  directly; it only knows `Enricher`.
- **Dependency injection.** The Anthropic client is injectable, so the adapter
  is unit-testable with a fake and never requires a live API in tests.
- **Graceful degradation.** If the `anthropic` SDK or an API key is absent,
  `available()` is False and the CLI falls back to `NullEnricher`.
- **Bounded cost.** Only module nodes are summarized, capped at `max_modules`,
  with the system prompt prompt-cached across calls.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Iterable

from ..domain.models import Fragment, Node

MODEL = "claude-opus-4-8"

_SYSTEM = (
    "You summarize source modules for a code knowledge graph. Given a module "
    "path and the names of the functions/classes it defines, reply with one "
    "concise sentence (max 18 words) describing the module's responsibility. "
    "Base it only on the names provided; do not speculate beyond them."
)

_FORMAT = {
    "format": {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
    }
}


class AnthropicEnricher:
    def __init__(self, model: str = MODEL, max_modules: int = 100,
                 client: object | None = None) -> None:
        self._model = model
        self._max_modules = max_modules
        self._client = client or self._make_client()

    @staticmethod
    def _make_client():
        try:
            import anthropic  # resolves ANTHROPIC_API_KEY from the environment
            return anthropic.Anthropic()
        except Exception:
            return None

    def available(self) -> bool:
        return self._client is not None

    def enrich(self, fragments: Iterable[Fragment]) -> Iterable[Fragment]:
        fragments = list(fragments)
        if self._client is None:
            return fragments

        budget = self._max_modules
        for frag in fragments:
            if budget <= 0:
                break
            module = next((n for n in frag.nodes if n.kind == "module"), None)
            symbols = [n.label for n in frag.nodes if n.kind != "module"]
            if module is None or not symbols:
                continue
            summary = self._summarize(module.path, symbols)
            if summary:
                frag.nodes = [
                    replace(n, meta={**n.meta, "summary": summary})
                    if n is module else n
                    for n in frag.nodes
                ]
                budget -= 1
        return fragments

    def _summarize(self, path: str, symbols: list[str]) -> str | None:
        prompt = f"Module: {path}\nDefines: {', '.join(symbols[:60])}"
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=256,
                system=[{"type": "text", "text": _SYSTEM,
                         "cache_control": {"type": "ephemeral"}}],
                output_config=_FORMAT,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception:
            return None
        if getattr(response, "stop_reason", None) == "refusal":
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            return json.loads(text)["summary"]
        except (ValueError, KeyError):
            return None
