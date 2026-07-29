from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from deepresearch_agent.schemas import EvaluationResult, Evidence


@dataclass(frozen=True)
class StoredChunk:
    id: str
    char_start: int
    char_end: int
    page_number: int | None
    effective_date: str
    content: str


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
    ) -> DocumentIngestResult: ...

    def rag_status(self) -> dict[str, int]: ...
