from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.rag.backends import QdrantDenseBackend, StorageLexicalBackend, chinese_lexical_terms
from deepresearch_agent.rag.qdrant_index import QdrantQueryHit
from deepresearch_agent.rag.search import RagSearchService, RetrievalFilter
from deepresearch_agent.schemas import BoundingBox, TextBoundingBox
from deepresearch_agent.storage import SQLiteStore, StoredChunk


class _StaticEmbedding:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


class _StaticIndex:
    def query(self, **_kwargs: object) -> list[QdrantQueryHit]:
        return [QdrantQueryHit("matched", 0.9), QdrantQueryHit("missing", 0.8)]


class RagBackendsTests(unittest.TestCase):
    def _store(self) -> SQLiteStore:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = SQLiteStore(Path(directory.name) / "rag.db")
        store.record_document_version(
            canonical_url="https://example.test/report",
            file_sha256="a" * 64,
            effective_date="2025-01-01",
            published_at="2025-03-01",
            chunks=[
                StoredChunk(
                    "matched", 0, 10, 1, "2025-01-01", "营业收入增长明显",
                    (TextBoundingBox(
                        text="营业收入", bbox=BoundingBox(page=1, x0=1, top=2, x1=3, bottom=4)
                    ),),
                    published_at="2025-03-01",
                ),
                StoredChunk(
                    "other", 10, 20, 1, "2025-01-01", "风险因素说明",
                    published_at="2025-03-01",
                ),
            ],
        )
        return store

    def test_chinese_tokenizer_and_lexical_backend_return_a_real_chunk(self) -> None:
        self.assertIn("营业", chinese_lexical_terms("营业收入"))
        backend = StorageLexicalBackend(store=self._store())
        results = backend.search(
            query="营业收入", filters=RetrievalFilter(as_of=date(2026, 1, 1)), limit=5
        )
        self.assertEqual([item.chunk_id for item in results], ["matched"])
        self.assertGreater(results[0].score or 0, 0)

    def test_requested_unmodeled_facets_fail_closed(self) -> None:
        backend = StorageLexicalBackend(store=self._store())
        results = backend.search(
            query="营业收入",
            filters=RetrievalFilter(as_of=date(2026, 1, 1), doc_types=("annual-report",)),
            limit=5,
        )
        self.assertEqual(results, [])

    def test_dense_backend_hydrates_only_ready_authoritative_chunks(self) -> None:
        backend = QdrantDenseBackend(
            store=self._store(), index=_StaticIndex(), embedding=_StaticEmbedding()  # type: ignore[arg-type]
        )
        results = backend.search(
            query="营业收入", filters=RetrievalFilter(as_of=date(2026, 1, 1)), limit=5
        )
        self.assertEqual([item.chunk_id for item in results], ["matched"])
        self.assertEqual(results[0].text, "营业收入增长明显")
        self.assertEqual(results[0].score, 0.9)
        self.assertEqual(results[0].bbox_index[0].bbox.page, 1)

    def test_finance_domain_alias_reaches_english_authoritative_chunks(self) -> None:
        store = self._store()
        store.record_document_version(
            canonical_url="https://example.test/alibaba",
            file_sha256="b" * 64,
            effective_date="2025-01-01",
            published_at="2025-03-01",
            chunks=[
                StoredChunk(
                    "alibaba", 0, 60, 1, "2025-01-01",
                    "Alibaba Group Holding Limited reported Total revenue.",
                    entity_id="baba",
                    published_at="2025-03-01",
                )
            ],
        )
        backend = StorageLexicalBackend(store=store)
        service = RagSearchService(
            lexical=backend,
            dense=backend,
            reranker=None,
            retrieval_top_k=10,
            rerank_top_n=8,
            rerank_enabled=False,
            rerank_fail_open=True,
            retrieval_domain=load_domain_pack("finance"),
        )

        result = service.search(query="阿里巴巴集团 Total revenue", as_of="2026-01-01")

        self.assertIn("alibaba", [item["chunk_id"] for item in result["candidates"]])


if __name__ == "__main__":
    unittest.main()
