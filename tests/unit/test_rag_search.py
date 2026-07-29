from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.domains.protocols import RetrievalFilterValues
from deepresearch_agent.rag.retrieval import FixtureRerankerProvider
from deepresearch_agent.rag.search import RagSearchService, RetrievalFilter, SearchChunk


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


if __name__ == "__main__":
    unittest.main()
