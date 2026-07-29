from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.domains.protocols import RetrievalFilterValues
from deepresearch_agent.rag.retrieval import FixtureRerankerProvider
from deepresearch_agent.rag.search import RagSearchService, RetrievalFilter, SearchChunk
from deepresearch_agent.tools.contracts import ToolErrorKind
from deepresearch_agent.tools.reliable_execution import ToolExecutionError
from deepresearch_agent.trajectory import TrajectoryRecorder, trajectory_recording
from deepresearch_agent.trajectory_replay import replay_recorded_rag_search


class StaticBackend:
    def __init__(self, chunks: list[SearchChunk]) -> None:
        self.chunks = chunks

    def search(self, *, query: str, filters: RetrievalFilter, limit: int) -> list[SearchChunk]:
        del query, filters
        return self.chunks[:limit]


class RecordingBackend(StaticBackend):
    def __init__(self, chunks: list[SearchChunk]) -> None:
        super().__init__(chunks)
        self.filters: list[RetrievalFilter] = []

    def search(self, *, query: str, filters: RetrievalFilter, limit: int) -> list[SearchChunk]:
        self.filters.append(filters)
        return super().search(query=query, filters=filters, limit=limit)


class FailingBackend:
    def search(self, **_kwargs: object) -> list[SearchChunk]:
        raise ToolExecutionError(ToolErrorKind.TIMEOUT, "simulated timeout")


class FinanceLikeRetrievalDomain:
    def retrieval_filter_values(self, query: str) -> RetrievalFilterValues:
        self.query = query
        return RetrievalFilterValues(doc_types=("annual-report",), period_labels=("2024",))


class RagSearchTests(unittest.TestCase):
    def test_requires_as_of_and_filters_future_chunks(self) -> None:
        old = SearchChunk("old", "答案", date(2025, 1, 1), "v1", 0, 2)
        future = SearchChunk("future", "未来答案", date(2027, 1, 1), "v2", 0, 4)
        service = RagSearchService(
            lexical=StaticBackend([old, future]),
            dense=StaticBackend([future, old]),
            reranker=FixtureRerankerProvider(),
            retrieval_top_k=10,
            rerank_top_n=5,
            rerank_enabled=True,
            rerank_fail_open=True,
        )
        with self.assertRaisesRegex(ValueError, "requires as_of"):
            service.search(query="问题", as_of="")

        result = service.search(query="问题", as_of="2026-01-01")
        self.assertEqual([item["chunk_id"] for item in result["candidates"]], ["old"])
        self.assertEqual(result["trace"].rerank_status, "ok")

    def test_disabled_rerank_does_not_require_a_provider(self) -> None:
        chunk = SearchChunk("a", "文本", date(2025, 1, 1), "v1", 0, 2)
        service = RagSearchService(
            lexical=StaticBackend([chunk]),
            dense=StaticBackend([]),
            reranker=None,
            retrieval_top_k=10,
            rerank_top_n=5,
            rerank_enabled=False,
            rerank_fail_open=True,
        )
        result = service.search(query="问题", as_of="2026-01-01")
        self.assertEqual(result["trace"].rerank_status, "disabled")
        self.assertEqual([item["chunk_id"] for item in result["candidates"]], ["a"])

    def test_service_uses_configured_index_version_when_call_has_none(self) -> None:
        chunk = SearchChunk("a", "文本", date(2025, 1, 1), "v1", 0, 2)
        backend = RecordingBackend([chunk])
        service = RagSearchService(
            lexical=backend,
            dense=backend,
            reranker=None,
            retrieval_top_k=10,
            rerank_top_n=5,
            rerank_enabled=False,
            rerank_fail_open=True,
            index_version="finance-v1",
        )

        service.search(query="问题", as_of="2026-01-01")

        self.assertEqual(backend.filters[0].index_version, "finance-v1")

    def test_search_records_a_redacted_index_version_trace_for_replay(self) -> None:
        chunk = SearchChunk("a", "文本", date(2025, 1, 1), "v1", 0, 2)
        service = RagSearchService(
            lexical=StaticBackend([chunk]), dense=StaticBackend([]), reranker=None,
            retrieval_top_k=10, rerank_top_n=5, rerank_enabled=False,
            rerank_fail_open=True, index_version="finance-v1",
        )
        recorder = TrajectoryRecorder(run_id="trace", request={})

        with trajectory_recording(recorder):
            service.search(query="不可写入轨迹的明文问题", as_of="2026-01-01")

        call = recorder.trajectory.tool_calls[0]
        self.assertEqual(call.tool_spec["name"], "rag_search")
        self.assertEqual(call.inputs["index_version"], "finance-v1")
        self.assertNotIn("不可写入轨迹的明文问题", str(call.inputs))

    def test_missing_reranker_fails_closed_when_fail_open_is_disabled(self) -> None:
        chunk = SearchChunk("a", "文本", date(2025, 1, 1), "v1", 0, 2)
        service = RagSearchService(
            lexical=StaticBackend([chunk]),
            dense=StaticBackend([]),
            reranker=None,
            retrieval_top_k=10,
            rerank_top_n=5,
            rerank_enabled=True,
            rerank_fail_open=False,
        )
        result = service.search(query="问题", as_of="2026-01-01")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["trace"].degradation.impact, "empty_result")

    def test_domain_values_are_injected_without_domain_logic_in_the_service(self) -> None:
        chunk = SearchChunk("a", "text", date(2025, 1, 1), "v1", 0, 4)
        backend = RecordingBackend([chunk])
        domain = FinanceLikeRetrievalDomain()
        service = RagSearchService(
            lexical=backend,
            dense=backend,
            reranker=None,
            retrieval_top_k=10,
            rerank_top_n=5,
            rerank_enabled=False,
            rerank_fail_open=True,
            retrieval_domain=domain,
        )

        service.search(query="annual performance", as_of="2026-01-01")

        self.assertEqual(domain.query, "annual performance")
        self.assertEqual(backend.filters[0].doc_types, ("annual-report",))
        self.assertEqual(backend.filters[0].period_labels, ("2024",))

    def test_returned_candidate_retains_all_backend_scores(self) -> None:
        lexical = SearchChunk("a", "文本", date(2025, 1, 1), "v1", 0, 2, score=0.25)
        dense = SearchChunk("a", "文本", date(2025, 1, 1), "v1", 0, 2, score=0.75)
        service = RagSearchService(
            lexical=StaticBackend([lexical]),
            dense=StaticBackend([dense]),
            reranker=FixtureRerankerProvider(),
            retrieval_top_k=10,
            rerank_top_n=5,
            rerank_enabled=True,
            rerank_fail_open=True,
        )

        candidate = service.search(query="文本", as_of="2026-01-01")["candidates"][0]

        self.assertEqual(candidate["lexical_score"], 0.25)
        self.assertEqual(candidate["dense_score"], 0.75)
        self.assertGreater(candidate["rrf_score"], 0)
        self.assertIsNotNone(candidate["rerank_score"])

    def test_backend_failure_is_explicit_degradation_not_a_fabricated_hit(self) -> None:
        service = RagSearchService(
            lexical=FailingBackend(),
            dense=StaticBackend([]),
            reranker=None,
            retrieval_top_k=10,
            rerank_top_n=5,
            rerank_enabled=False,
            rerank_fail_open=True,
        )

        result = service.search(query="问题", as_of="2026-01-01")

        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["trace"].degradation.tool, "rag_search")
        self.assertEqual(result["trace"].degradation.reason, ToolErrorKind.TIMEOUT)

    def test_degraded_rerank_replays_the_recorded_rrf_order_without_provider_call(self) -> None:
        class FailingReranker:
            def rerank(self, *_args: object, **_kwargs: object) -> object:
                raise ToolExecutionError(ToolErrorKind.TIMEOUT, "rerank unavailable")

        chunks = [
            SearchChunk("a", "甲", date(2025, 1, 1), "v1", 0, 1),
            SearchChunk("b", "乙", date(2025, 1, 1), "v1", 1, 2),
        ]
        service = RagSearchService(
            lexical=StaticBackend(chunks), dense=StaticBackend([]), reranker=FailingReranker(),
            retrieval_top_k=10, rerank_top_n=8, rerank_enabled=True,
            rerank_fail_open=True, index_version="idx-v1",
        )
        recorder = TrajectoryRecorder(run_id="degraded", request={})
        with trajectory_recording(recorder):
            result = service.search(query="问题", as_of="2026-01-01")

        self.assertEqual(result["trace"].rerank_status, "degraded")
        self.assertEqual(
            replay_recorded_rag_search(recorder.trajectory.tool_calls[0]),
            tuple(item["chunk_id"] for item in result["candidates"]),
        )


if __name__ == "__main__":
    unittest.main()
