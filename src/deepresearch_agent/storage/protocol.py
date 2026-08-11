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
    published_at_source: str = ""


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
    filing_date: str = ""
    published_at_source: str = ""


@dataclass(frozen=True)
class MemoryRecord:
    """One durable memory row.

    R122. ``EpisodicMemory`` and ``ProceduralMemory`` declare
    ``lifecycle = "cross_run"`` and were plain in-process dicts: the storage
    schema had no memory table, nothing wrote one, and the only production
    construction site built an empty object per engine. Both flags could be
    switched on and read nothing, which `tests/unit/test_memory_flags_need_a_
    prior_run.py` recorded rather than fixed.

    The row is deliberately generic -- a namespace, the key a reader queries by,
    an id unique within that key, and an opaque payload. Storage does not import
    the memory layer, so a new memory kind needs no new protocol method and no
    second implementation to drift.
    """

    namespace: str
    scope_key: str
    record_id: str
    payload: str
    created_at: str = ""


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
        published_at_source: str = "",
    ) -> DocumentIngestResult: ...

    def rag_status(self) -> dict[str, int]: ...

    def list_ready_chunks(self, *, as_of: str) -> list[ResolvedChunk]: ...

    def resolve_ready_chunks(self, chunk_ids: list[str], *, as_of: str) -> list[ResolvedChunk]: ...

    def write_memory_record(self, record: MemoryRecord) -> None: ...

    def list_memory_records(self, namespace: str, scope_key: str) -> list[MemoryRecord]: ...
