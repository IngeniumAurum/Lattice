"""Enricher port + a no-op default.

Semantic enrichment (summarizing docs, inferring cross-file relations) is
optional and provider-agnostic. A real adapter wraps Anthropic / OpenAI / Ollama
behind this same contract; the pipeline never names a provider.
"""

from __future__ import annotations

from typing import Iterable

from ..domain.models import Fragment


class NullEnricher:
    """Identity enrichment — used when no LLM backend is configured."""

    def enrich(self, fragments: Iterable[Fragment]) -> Iterable[Fragment]:
        return fragments
