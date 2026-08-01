"""Auditable retrieval primitives; candidates never become Evidence directly."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepresearch_agent.rag.ingest import ingest_corpus

__all__ = ["ingest_corpus"]


def __getattr__(name: str) -> object:
    """Avoid loading PDF ingestion for consumers of retrieval-only modules."""
    if name == "ingest_corpus":
        from deepresearch_agent.rag.ingest import ingest_corpus

        return ingest_corpus
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
