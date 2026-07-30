from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents.researcher import ResearcherAgent
from deepresearch_agent.agents.extractor import ExtractorAgent
from deepresearch_agent.schemas import RetrievalReference, Source, SubQuestion


class _RagSearch:
    def search(
        self, *, query: str, as_of: str, context: object | None = None
    ) -> dict[str, object]:
        del context
        return {
            "candidates": [
                {
                    "chunk_id": "chunk-1",
                    "document_version_id": "version-1",
                    "source_url": "https://example.test/annual-report.pdf",
                    "text": "权威原文片段",
                    "index_version": "finance-v1",
                    "char_start": 10,
                    "char_end": 20,
                    "bbox_index": [
                        {
                            "text": "权威原文片段",
                            "bbox": {"page": 1, "x0": 1.0, "top": 2.0, "x1": 3.0, "bottom": 4.0},
                        }
                    ],
                }
            ],
            "trace": {"query": query, "as_of": as_of},
        }


class RagResearcherTests(unittest.TestCase):
    def test_rag_candidates_are_adapted_as_locatable_sources_alongside_other_tools(self) -> None:
        researcher = ResearcherAgent(rag_search=_RagSearch(), as_of=date(2026, 1, 1))
        sources, records, calls, exhausted, _ = researcher.research_with_budget(
            SubQuestion(id="q", question="问题", search_queries=["检索问题"]),
            enable_web_search=False,
            enable_rag_search=True,
            max_search_calls=0,
        )

        self.assertEqual(calls, 0)
        self.assertFalse(exhausted)
        self.assertEqual(sources[0].url, "https://example.test/annual-report.pdf#chunk=chunk-1")
        self.assertEqual(sources[0].content, "权威原文片段")
        self.assertEqual(sources[0].retrieval_ref.chunk_id, "chunk-1")
        self.assertEqual(sources[0].bbox_index[0].bbox.page, 1)
        self.assertEqual(records[0].query, "[rag_search] 检索问题")

    def test_invalid_rag_candidate_is_rejected_instead_of_becoming_a_source(self) -> None:
        class InvalidRag:
            def search(self, **_kwargs: object) -> dict[str, object]:
                return {"candidates": [{"chunk_id": "missing-identity"}], "trace": {}}

        researcher = ResearcherAgent(rag_search=InvalidRag(), as_of=date(2026, 1, 1))
        with self.assertRaisesRegex(ValueError, "authoritative source identity"):
            researcher.research_with_budget(
                SubQuestion(id="q", question="问题", search_queries=[]),
                enable_web_search=False,
                enable_rag_search=True,
                max_search_calls=0,
            )

    def test_extractor_rejects_raw_retrieval_candidate(self) -> None:
        with self.assertRaisesRegex(TypeError, "not retrieval candidates"):
            ExtractorAgent().extract(
                "run",
                SubQuestion(id="q", question="问题", search_queries=[]),
                [
                    {
                        "chunk_id": "chunk-1",
                        "text": "不应绕过 Source 适配直接成为 Evidence。",
                    }
                ],  # type: ignore[list-item]
            )

    def test_extractor_persists_retrieval_reference_from_source_metadata(self) -> None:
        source = Source(
            id="rag:chunk-1",
            title="retrieval chunk",
            url="https://example.test/report#chunk=chunk-1",
            source_type="rag_chunk",
            content="这是足够长的权威问题原文片段，用于验证检索引用可以进入既有证据存储并保持完整可追溯性。",
            retrieval_ref=RetrievalReference(
                chunk_id="chunk-1",
                document_version_id="version-1",
                index_version="finance-v1",
                char_start=10,
                char_end=30,
            ),
        )
        evidence = ExtractorAgent().extract(
            "run", SubQuestion(id="q", question="问题", search_queries=[]), [source]
        )
        self.assertEqual(evidence[0].retrieval_ref, source.retrieval_ref)


if __name__ == "__main__":
    unittest.main()
