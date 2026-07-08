from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents.researcher import ResearcherAgent
from deepresearch_agent.schemas import Source, SubQuestion


class CountingSearchProvider:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        self.queries.append(query)
        return [
            Source(
                id=f"source-{len(self.queries)}",
                title=f"Source {len(self.queries)}",
                url=f"https://example.com/{len(self.queries)}",
                source_type=source_type or "web",
                published_at=date(2026, 1, 1),
                content=f"content for {query}",
            )
        ]


class ResearcherSearchBudgetTests(unittest.TestCase):
    def test_research_stops_searching_after_per_run_limit(self) -> None:
        provider = CountingSearchProvider()
        researcher = ResearcherAgent(search_tool=provider, max_searches_per_run=2)
        sub_question = SubQuestion(
            id="sq1",
            question="question",
            search_queries=["q1", "q2", "q3"],
        )

        _sources, records = researcher.research(sub_question)

        self.assertEqual(provider.queries, ["q1", "q2"])
        self.assertEqual(records[-1].query, "[search_limit_exceeded] q3")
        self.assertEqual(records[-1].source_ids, [])

    def test_reset_search_budget_starts_new_run(self) -> None:
        provider = CountingSearchProvider()
        researcher = ResearcherAgent(search_tool=provider, max_searches_per_run=1)

        researcher.retry("q1")
        first_sources, first_record = researcher.retry("q2")
        researcher.reset_search_budget()
        second_sources, second_record = researcher.retry("q3")

        self.assertEqual(first_sources, [])
        self.assertEqual(first_record.query, "[search_limit_exceeded] q2")
        self.assertEqual(len(second_sources), 1)
        self.assertEqual(second_record.query, "q3")


if __name__ == "__main__":
    unittest.main()
