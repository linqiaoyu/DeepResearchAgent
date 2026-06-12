from __future__ import annotations

from typing import Protocol

from datetime import date

from deepresearch_agent.schemas import Source, StructuredDataRecord, SymbolInfo


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


class StructuredDataProvider(Protocol):
    """Structured finance data boundary for fixture and AKShare providers."""

    def symbol_resolve(self, company_name: str) -> SymbolInfo | None:
        """Resolve a company name to a normalized A-share symbol."""

    def financial_indicators(
        self,
        symbol: str,
        periods: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> list[StructuredDataRecord]:
        """Return whitelisted financial indicators for a symbol and report periods."""

    def price_history(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[StructuredDataRecord]:
        """Return normalized historical price summary records."""
