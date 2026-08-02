from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
from typing import Protocol

from deepresearch_agent.domains.protocols import RetrievalDomain
from deepresearch_agent.schemas import TextBoundingBox
from deepresearch_agent.rag.retrieval import (
    RerankerProvider,
    rerank_or_degrade,
    rrf_fuse,
)
from deepresearch_agent.tools.contracts import DegradationEvent
from deepresearch_agent.tools.capability_registry import RAG_SEARCH_TOOL_SPEC
from deepresearch_agent.tools.reliable_execution import (
    ReliableToolExecutor,
    RunToolContext,
    ToolExecutionError,
    classify_tool_error,
)
from deepresearch_agent.trajectory import ToolCallTrace, active_trajectory_recorder


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
    bbox_index: tuple[TextBoundingBox, ...] = ()
    published_at: date | None = None


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
        executor: ReliableToolExecutor | None = None,
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
        self.executor = executor or ReliableToolExecutor()

    @property
    def fidelity(self) -> str:
        backends = [self.lexical, self.dense]
        if self.rerank_enabled:
            backends.append(self.reranker)
        values = [getattr(backend, "fidelity", None) for backend in backends]
        allowed = {"real", "fixture", "replay"}
        if any(value not in allowed for value in values):
            return "unknown"
        unique = set(values)
        return unique.pop() if len(unique) == 1 else "mixed"

    def search(
        self,
        *,
        query: str,
        as_of: str,
        filters: RetrievalFilter | None = None,
        filter_query: str | None = None,
        context: RunToolContext | None = None,
    ) -> dict[str, object]:
        if not as_of:
            raise ValueError("rag_search requires as_of")
        effective_filters = filters or RetrievalFilter()
        if effective_filters.as_of is not None and effective_filters.as_of.isoformat() != as_of:
            raise ValueError("as_of must match RetrievalFilter.as_of when both are supplied")
        domain_values = (
            self.retrieval_domain.retrieval_filter_values(filter_query or query)
            if self.retrieval_domain is not None
            else None
        )
        expanded_query = (
            self.retrieval_domain.expand_retrieval_query(query)
            if self.retrieval_domain is not None
            else query
        )
        effective_filters = RetrievalFilter(
            doc_types=effective_filters.doc_types or (domain_values.doc_types if domain_values else ()),
            entity_ids=effective_filters.entity_ids or (domain_values.entity_ids if domain_values else ()),
            period_labels=effective_filters.period_labels or (domain_values.period_labels if domain_values else ()),
            as_of=date.fromisoformat(as_of),
            index_version=effective_filters.index_version or self.index_version,
        )
        run_context = context or RunToolContext.for_run()

        def search_backends() -> tuple[list[SearchChunk], list[SearchChunk]]:
            run_context.consume_external_request("search", tool="rag_search")
            lexical = self.lexical.search(
                query=expanded_query, filters=effective_filters, limit=self.retrieval_top_k
            )
            dense = self.dense.search(
                query=expanded_query, filters=effective_filters, limit=self.retrieval_top_k
            )
            return lexical, dense

        tool_result = self.executor.execute(
            RAG_SEARCH_TOOL_SPEC,
            search_backends,
            run_context,
            degrade=True,
            degraded_value=([], []),
            impact="empty_result",
        )
        if not tool_result.ok:
            error = tool_result.error
            if error is None:
                error = ToolExecutionError(
                    classify_tool_error(RuntimeError("rag_search failed")),
                    "rag_search failed without an error",
                )
            degradation = DegradationEvent(
                tool="rag_search",
                reason=error.kind,
                impact="empty_result",
                attempts=tool_result.attempts,
            )
            result = {
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
            self._record_trace(query=query, as_of=as_of, filters=effective_filters, result=result)
            return result
        lexical, dense = tool_result.value
        if not lexical and not dense:
            degradation = DegradationEvent(
                tool="rag_search",
                reason="not_found",
                impact="empty_result",
                attempts=tool_result.attempts,
            )
            result = {
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
            self._record_trace(query=query, as_of=as_of, filters=effective_filters, result=result)
            return result
        permitted = {
            chunk.chunk_id: chunk
            for chunk in [*lexical, *dense]
            if (chunk.published_at or chunk.effective_date) <= effective_filters.as_of
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
                        query=expanded_query,
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
        if degradation is not None:
            run_context.degradation_events.append(degradation)
        trace = RetrievalTrace(
            index_version=effective_filters.index_version or "unspecified",
            lexical_count=len(lexical),
            dense_count=len(dense),
            fused_count=len(fused),
            delivered_count=len(delivered),
            rerank_status=rerank_status,
            degradation=degradation,
        )
        result = {
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
                    "published_at": (
                        permitted[candidate.chunk_id].published_at.isoformat()
                        if permitted[candidate.chunk_id].published_at
                        else None
                    ),
                    "report_period_end": permitted[candidate.chunk_id].effective_date.isoformat(),
                    "index_version": effective_filters.index_version or "unspecified",
                    "char_start": permitted[candidate.chunk_id].char_start,
                    "char_end": permitted[candidate.chunk_id].char_end,
                    "bbox_index": [
                        item.model_dump(mode="json")
                        for item in permitted[candidate.chunk_id].bbox_index
                    ],
                }
                for candidate in delivered
            ],
            "trace": trace,
        }
        self._record_trace(query=query, as_of=as_of, filters=effective_filters, result=result)
        return result

    @staticmethod
    def _record_trace(
        *, query: str, as_of: str, filters: RetrievalFilter, result: dict[str, object]
    ) -> None:
        recorder = active_trajectory_recorder()
        if recorder is None:
            return
        candidates = result.get("candidates", [])
        candidate_ids = [
            item.get("chunk_id")
            for item in candidates
            if isinstance(item, dict) and isinstance(item.get("chunk_id"), str)
        ]
        trace = result.get("trace")
        recorder.record_tool_call(
            ToolCallTrace(
                tool_spec=RAG_SEARCH_TOOL_SPEC.model_dump(mode="json"),
                inputs={
                    "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                    "as_of": as_of,
                    "index_version": filters.index_version,
                },
                result={
                    "candidate_ids": candidate_ids,
                    "rerank_status": getattr(trace, "rerank_status", None),
                    "degradation_reason": (
                        str(trace.degradation.reason)
                        if getattr(trace, "degradation", None) is not None
                        else None
                    ),
                },
                attempts=1,
            )
        )
