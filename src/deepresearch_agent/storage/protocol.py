from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from deepresearch_agent.schemas import EvaluationResult, Evidence, TextBoundingBox


@dataclass(frozen=True)
class StoredChunk:
    id: str
    char_start: int
    char_end: int
    page_number: int | None
    effective_date: str
    content: str
    bbox_index: tuple[TextBoundingBox, ...] = ()
    entity_id: str = ""
    published_at: str = ""


@dataclass(frozen=True)
class ResolvedChunk:
    """A ready chunk resolved from the authoritative relational store."""

    id: str
    document_version_id: str
    canonical_url: str
    char_start: int
    char_end: int
    page_number: int | None
    effective_date: str
    content: str
    bbox_index: tuple[TextBoundingBox, ...] = ()
    entity_id: str = ""
    published_at: str = ""


@dataclass(frozen=True)
class DocumentIngestResult:
    document_id: str
    document_version_id: str
    active_chunks: int
    superseded_chunks: int


@runtime_checkable
class StorageProtocol(Protocol):
    """Persistence boundary used by the workflow.

    Implementations must preserve evidence insertion order for a research run.
    More specialized RAG persistence APIs are intentionally kept outside this
    stable workflow-facing contract until their data model is implemented.
    """

    def add_evidence_many(self, items: list[Evidence]) -> None: ...

    def list_evidence(self, research_id: str) -> list[Evidence]: ...

    def save_evaluation(self, result: EvaluationResult) -> None: ...

    def latest_metrics(self) -> list[EvaluationResult]: ...

    def record_document_version(
        self,
        *,
        canonical_url: str,
        file_sha256: str,
        effective_date: str,
        chunks: list[StoredChunk],
        published_at: str | None = None,
    ) -> DocumentIngestResult: ...

    def rag_status(self) -> dict[str, int]: ...

    def list_ready_chunks(self, *, as_of: str) -> list[ResolvedChunk]: ...

    def resolve_ready_chunks(self, chunk_ids: list[str], *, as_of: str) -> list[ResolvedChunk]: ...
