from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from deepresearch_agent.agents import CriticAgent, ExtractorAgent
from deepresearch_agent.agents.researcher import ResearcherAgent
from deepresearch_agent.rag.backends import StorageLexicalBackend
from deepresearch_agent.rag.chunking import chunk_located_text
from deepresearch_agent.rag.ingest import _extract, ingest_and_persist, ingest_corpus
from deepresearch_agent.rag.search import RagSearchService
from deepresearch_agent.schemas import (
    ResearchPlan,
    ResearchState,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.storage import SQLiteStore, StoredChunk


class RagIngestTests(unittest.TestCase):
    def _manifest(self, path: Path, text: str) -> dict[str, object]:
        encoded = text.encode("utf-8")
        return {
            "documents": [{
                "path": path.name,
                "url": "https://example.test/document",
                "sha256": hashlib.sha256(encoded).hexdigest(),
                "bytes": len(encoded),
                "retrieved_at": "2026-07-29T00:00:00Z",
                "public_accessibility": "public",
                "effective_date": "2025-12-31",
            }]
        }

    def test_ingest_is_deterministic_and_all_chunks_are_located(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.txt"
            text = "a" * 3000
            source.write_text(text, encoding="utf-8")
            manifest = root / "corpus.json"
            manifest.write_text(json.dumps(self._manifest(source, text)), encoding="utf-8")

            first = ingest_corpus(input_dir=root, corpus_path=manifest)
            second = ingest_corpus(input_dir=root, corpus_path=manifest)

        self.assertEqual([item.id for item in first], [item.id for item in second])
        self.assertTrue(all(item.char_end > item.char_start for item in first))
        self.assertTrue(all(item.effective_date == "2025-12-31" for item in first))

    def test_as_of_filters_on_published_at_not_report_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "research.db")
            chunk = StoredChunk(
                id="published-late", char_start=0, char_end=4, page_number=None,
                effective_date="2024-03-31", content="late", published_at="2024-06-21",
            )
            store.record_document_version(
                canonical_url="https://example.test/late", file_sha256="b" * 64,
                effective_date="2024-03-31", published_at="2024-06-21", chunks=[chunk],
            )
            before = store.list_ready_chunks(as_of="2024-04-01")
            after = store.list_ready_chunks(as_of="2024-07-01")
        self.assertEqual(before, [])
        self.assertEqual([item.id for item in after], ["published-late"])

    def test_ingest_rejects_manifest_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.txt"
            source.write_text("actual", encoding="utf-8")
            manifest = root / "corpus.json"
            manifest.write_text(json.dumps(self._manifest(source, "expected")), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                ingest_corpus(input_dir=root, corpus_path=manifest)

    def test_persisted_versions_are_idempotent_then_superseded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "report.txt"
            first_text = "a" * 3000
            source.write_text(first_text, encoding="utf-8")
            manifest = root / "corpus.json"
            manifest.write_text(json.dumps(self._manifest(source, first_text)), encoding="utf-8")
            store = SQLiteStore(root / "research.db")

            first = ingest_and_persist(input_dir=root, corpus_path=manifest, store=store)
            self.assertEqual(
                {chunk.entity_id for chunk in store.list_ready_chunks(as_of="9999-12-31")},
                {"report"},
            )
            repeated = ingest_and_persist(input_dir=root, corpus_path=manifest, store=store)

            second_text = "b" * 3000
            source.write_text(second_text, encoding="utf-8")
            manifest.write_text(json.dumps(self._manifest(source, second_text)), encoding="utf-8")
            changed = ingest_and_persist(input_dir=root, corpus_path=manifest, store=store)

            status = store.rag_status()
        self.assertEqual(first.superseded_chunks, 0)
        self.assertGreater(first.added_chunks, 0)
        self.assertEqual(first.removed_chunks, 0)
        self.assertEqual(repeated.superseded_chunks, 0)
        self.assertEqual(repeated.added_chunks, 0)
        self.assertEqual(repeated.removed_chunks, 0)
        self.assertGreater(changed.superseded_chunks, 0)
        self.assertEqual(status["active_chunks"], changed.chunks)
        self.assertEqual(status["superseded_chunks"], changed.superseded_chunks)

    def test_reingest_replaces_stale_derived_chunk_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "research.db")
            first = StoredChunk(
                id="old-layout",
                char_start=0,
                char_end=3,
                page_number=None,
                effective_date="2025-12-31",
                content="old",
            )
            replacement = StoredChunk(
                id="new-layout",
                char_start=0,
                char_end=6,
                page_number=None,
                effective_date="2025-12-31",
                content="newest",
            )
            store.record_document_version(
                canonical_url="https://example.test/document",
                file_sha256="a" * 64,
                effective_date="2025-12-31",
                chunks=[first],
            )
            store.record_document_version(
                canonical_url="https://example.test/document",
                file_sha256="a" * 64,
                effective_date="2025-12-31",
                chunks=[replacement],
            )
            chunks = store.list_ready_chunks(as_of="2025-12-31")

        self.assertEqual([chunk.id for chunk in chunks], ["new-layout"])

    def test_storage_rejects_invalid_chunk_location_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(Path(directory) / "research.db")
            for name, chunk, message in (
                (
                    "file_hash",
                    StoredChunk("bad-hash", 0, 4, None, "2025-12-31", "text"),
                    "SHA-256",
                ),
                (
                    "char_range",
                    StoredChunk("bad-range", 5, 5, None, "2025-12-31", "text"),
                    "character ranges",
                ),
                (
                    "page",
                    StoredChunk("bad-page", 0, 4, 0, "2025-12-31", "text"),
                    "page numbers",
                ),
            ):
                with self.subTest(mutation=name), self.assertRaisesRegex(ValueError, message):
                    store.record_document_version(
                        canonical_url=f"https://example.test/{name}",
                        file_sha256=("invalid" if name == "file_hash" else ("b" * 64 if name == "char_range" else "c" * 64)),
                        effective_date="2025-12-31",
                        chunks=[chunk],
                    )

    def test_pdf_words_preserve_exact_page_bbox_into_chunks(self) -> None:
        class Page:
            def extract_words(self) -> list[dict[str, object]]:
                return [
                    {"text": "Total", "x0": 1.0, "top": 2.0, "x1": 3.0, "bottom": 4.0},
                    {"text": "revenue", "x0": 5.0, "top": 2.0, "x1": 8.0, "bottom": 4.0},
                ]

        class Pdf:
            pages = [Page()]

            def __enter__(self) -> "Pdf":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        with patch("deepresearch_agent.rag.ingest.pdfplumber.open", return_value=Pdf()):
            sections = _extract(Path("public-report.pdf"))
        chunks = chunk_located_text(
            document_sha256="a" * 64,
            sections=sections,
            effective_date="2025-12-31",
        )

        self.assertEqual(sections[0].text, "Total revenue")
        self.assertEqual(chunks[0].bbox_index[0].bbox.page, 1)
        self.assertEqual(chunks[0].bbox_index[1].text, "revenue")

    def test_pdf_chunk_bbox_survives_retrieval_source_extraction_and_critic(self) -> None:
        class Page:
            def extract_words(self) -> list[dict[str, object]]:
                return [
                    {
                        "text": word,
                        "x0": float(index * 10),
                        "top": 2.0,
                        "x1": float(index * 10 + 8),
                        "bottom": 12.0,
                    }
                    for index, word in enumerate(
                        "Total revenue was 42 million dollars according to the annual report.".split()
                    )
                ]

        class Pdf:
            pages = [Page()]

            def __enter__(self) -> "Pdf":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "issuer_2025.pdf"
            source.write_bytes(b"fixture PDF bytes; layout extraction is mocked below")
            manifest = root / "corpus.json"
            manifest.write_text(
                json.dumps(self._manifest(source, source.read_bytes().decode("utf-8"))),
                encoding="utf-8",
            )
            store = SQLiteStore(root / "research.db")
            with patch("deepresearch_agent.rag.ingest.pdfplumber.open", return_value=Pdf()):
                ingest_and_persist(input_dir=root, corpus_path=manifest, store=store)

            backend = StorageLexicalBackend(store=store)
            search = RagSearchService(
                lexical=backend,
                dense=backend,
                reranker=None,
                retrieval_top_k=4,
                rerank_top_n=1,
                rerank_enabled=False,
                rerank_fail_open=False,
                index_version="test-pdf-bbox",
            )
            result = search.search(query="Total revenue", as_of="2026-01-01")
            candidate = result["candidates"][0]
            assert isinstance(candidate, dict)
            source_from_candidate = ResearcherAgent._rag_source(candidate)

        self.assertEqual(source_from_candidate.url.split("#chunk=")[0], "https://example.test/document")
        self.assertEqual(source_from_candidate.bbox_index[0].bbox.page, 1)
        self.assertEqual(source_from_candidate.bbox_index[0].text, "Total")

        sub_question = SubQuestion(
            id="revenue",
            question="What was total revenue?",
            search_queries=["Total revenue"],
            structured_data_requests=[
                StructuredDataRequest(
                    capability="financial_indicators",
                    metrics=["revenue"],
                    periods=["2025"],
                )
            ],
        )
        evidence = ExtractorAgent().extract("pdf-bbox-run", sub_question, [source_from_candidate])
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].retrieval_ref, source_from_candidate.retrieval_ref)

        state = ResearchState(topic="PDF revenue", plan=ResearchPlan(
            topic="PDF revenue",
            sub_questions=[sub_question],
            success_criteria=["retrieve the requested figures"],
        ))
        state.evidence_store = evidence
        critique = CriticAgent(today=date(2026, 1, 1)).critique(state)
        self.assertTrue(critique.passed, critique.issues)


if __name__ == "__main__":
    unittest.main()
