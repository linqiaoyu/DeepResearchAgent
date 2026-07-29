from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from deepresearch_agent.domains.protocols import RetrievalDomain
from deepresearch_agent.rag.retrieval import (
    RerankerProvider,
    rerank_or_degrade,
    rrf_fuse,
)
from deepresearch_agent.tools.contracts import DegradationEvent
from deepresearch_agent.tools.reliable_execution import ToolExecutionError, classify_tool_error


@dataclass(frozen=True)
class RetrievalFilter:
    doc_types: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    period_labels: tuple[str, ...] = ()
    as_of: date | None = None
    index_version: str | None = None


@dataclass(frozen=True)
class SearchChunk:
    chunk_id: str
    text: str
    effective_date: date
    document_version_id: str
    char_start: int
    char_end: int
    score: float | None = None
    source_url: str = ""


@dataclass(frozen=True)
class RetrievalTrace:
    index_version: str
    lexical_count: int
    dense_count: int
    fused_count: int
    delivered_count: int
    rerank_status: str
    degradation: DegradationEvent | None = None
    dropped_unresolvable: int = 0


class RetrievalBackend(Protocol):
    def search(self, *, query: str, filters: RetrievalFilter, limit: int) -> list[SearchChunk]: ...


class RagSearchService:
    """Backend-neutral hybrid retrieval with an explicit as-of boundary."""

    fidelity = "fixture"

    def __init__(
        self,
        *,
        lexical: RetrievalBackend,
        dense: RetrievalBackend,
        reranker: RerankerProvider | None,
        retrieval_top_k: int,
        rerank_top_n: int,
        rerank_enabled: bool,
        rerank_fail_open: bool,
        retrieval_domain: RetrievalDomain | None = None,
        index_version: str | None = None,
    ) -> None:
        if retrieval_top_k < 1 or rerank_top_n < 1:
            raise ValueError("retrieval_top_k and rerank_top_n must be positive")
        self.lexical = lexical
        self.dense = dense
        self.reranker = reranker
        self.retrieval_top_k = retrieval_top_k
        self.rerank_top_n = rerank_top_n
        self.rerank_enabled = rerank_enabled
        self.rerank_fail_open = rerank_fail_open
        self.retrieval_domain = retrieval_domain
        self.index_version = index_version

    def search(
        self, *, query: str, as_of: str, filters: RetrievalFilter | None = None
    ) -> dict[str, object]:
        if not as_of:
            raise ValueError("rag_search requires as_of")
        effective_filters = filters or RetrievalFilter()
        if effective_filters.as_of is not None and effective_filters.as_of.isoformat() != as_of:
            raise ValueError("as_of must match RetrievalFilter.as_of when both are supplied")
        domain_values = (
            self.retrieval_domain.retrieval_filter_values(query)
            if self.retrieval_domain is not None
            else None
        )
        effective_filters = RetrievalFilter(
            doc_types=effective_filters.doc_types or (domain_values.doc_types if domain_values else ()),
            entity_ids=effective_filters.entity_ids or (domain_values.entity_ids if domain_values else ()),
            period_labels=effective_filters.period_labels or (domain_values.period_labels if domain_values else ()),
            as_of=date.fromisoformat(as_of),
            index_version=effective_filters.index_version or self.index_version,
        )
        try:
            lexical = self.lexical.search(
                query=query, filters=effective_filters, limit=self.retrieval_top_k
            )
            dense = self.dense.search(
                query=query, filters=effective_filters, limit=self.retrieval_top_k
            )
        except BaseException as exc:
            error = exc if isinstance(exc, ToolExecutionError) else ToolExecutionError(
                classify_tool_error(exc), str(exc)
            )
            degradation = DegradationEvent(
                tool="rag_search", reason=error.kind, impact="empty_result", attempts=1
            )
            return {
                "candidates": [],
                "trace": RetrievalTrace(
                    index_version=effective_filters.index_version or "unspecified",
                    lexical_count=0,
                    dense_count=0,
                    fused_count=0,
                    delivered_count=0,
                    rerank_status="not_attempted",
                    degradation=degradation,
                ),
            }
        permitted = {
            chunk.chunk_id: chunk
            for chunk in [*lexical, *dense]
            if chunk.effective_date <= effective_filters.as_of
        }
        fused = rrf_fuse(
            lexical_ids=[chunk.chunk_id for chunk in lexical if chunk.chunk_id in permitted],
            dense_ids=[chunk.chunk_id for chunk in dense if chunk.chunk_id in permitted],
            texts={identifier: chunk.text for identifier, chunk in permitted.items()},
            top_k=self.retrieval_top_k,
            lexical_scores={
                chunk.chunk_id: chunk.score
                for chunk in lexical
                if chunk.chunk_id in permitted and chunk.score is not None
            },
            dense_scores={
                chunk.chunk_id: chunk.score
                for chunk in dense
                if chunk.chunk_id in permitted and chunk.score is not None
            },
        )
        degradation: DegradationEvent | None = None
        rerank_status = "disabled"
        delivered = fused[: self.rerank_top_n]
        if self.rerank_enabled:
            if self.reranker is None:
                degradation = DegradationEvent(
                    tool="rerank",
                    reason="permanent",
                    impact="rrf_top_n_used" if self.rerank_fail_open else "empty_result",
                    attempts=0,
                )
                if not self.rerank_fail_open:
                    delivered = []
                rerank_status = "degraded"
            else:
                try:
                    delivered, degradation = rerank_or_degrade(
                        provider=self.reranker,
                        query=query,
                        candidates=fused,
                        top_n=self.rerank_top_n,
                        fail_open=self.rerank_fail_open,
                    )
                    rerank_status = "degraded" if degradation else "ok"
                except ToolExecutionError as exc:
                    degradation = DegradationEvent(
                        tool="rerank", reason=exc.kind, impact="empty_result", attempts=1
                    )
                    delivered = []
                    rerank_status = "degraded"
        trace = RetrievalTrace(
            index_version=effective_filters.index_version or "unspecified",
            lexical_count=len(lexical),
            dense_count=len(dense),
            fused_count=len(fused),
            delivered_count=len(delivered),
            rerank_status=rerank_status,
            degradation=degradation,
        )
        return {
            "candidates": [
                {
                    "chunk_id": candidate.chunk_id,
                    "text": candidate.text,
                    "lexical_rank": candidate.lexical_rank,
                    "dense_rank": candidate.dense_rank,
                    "lexical_score": candidate.lexical_score,
                    "dense_score": candidate.dense_score,
                    "rrf_score": candidate.rrf_score,
                    "rerank_score": candidate.rerank_score,
                    "document_version_id": permitted[candidate.chunk_id].document_version_id,
                    "source_url": permitted[candidate.chunk_id].source_url,
                    "index_version": effective_filters.index_version or "unspecified",
                    "char_start": permitted[candidate.chunk_id].char_start,
                    "char_end": permitted[candidate.chunk_id].char_end,
                }
                for candidate in delivered
            ],
            "trace": trace,
        }
