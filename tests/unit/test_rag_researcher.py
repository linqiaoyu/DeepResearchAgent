from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents.researcher import ResearcherAgent
from deepresearch_agent.schemas import SubQuestion


class _RagSearch:
    def search(self, *, query: str, as_of: str) -> dict[str, object]:
        return {
            "candidates": [
                {
                    "chunk_id": "chunk-1",
                    "document_version_id": "version-1",
                    "source_url": "https://example.test/annual-report.pdf",
                    "text": "权威原文片段",
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


if __name__ == "__main__":
    unittest.main()
