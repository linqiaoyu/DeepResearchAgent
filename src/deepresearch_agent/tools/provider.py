from __future__ import annotations

from typing import Protocol

from deepresearch_agent.schemas import Source


class SearchProvider(Protocol):
    """Search boundary for deterministic fixtures and optional real providers."""

    def search(
        self,
        query: str,
        top_k: int = 3,
        source_type: str | None = None,
    ) -> list[Source]:
        """Return ranked sources for a query."""


class FetchProvider(Protocol):
    """Optional fetch boundary for providers that can hydrate a source by URL."""

    def fetch(self, url: str) -> Source | None:
        """Return a source for a URL when supported."""
