from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents.researcher import ResearcherAgent
from deepresearch_agent.schemas import (
    Source,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.tools import ToolErrorKind, ToolExecutionError


class CountingSearchProvider:
    search_counts_toward_budget = True

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.fetched_urls: list[str] = []

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

    def fetch(self, url: str) -> Source:
        self.fetched_urls.append(url)
        return Source(
            id=f"fetched-{len(self.fetched_urls)}",
            title="Fetched disclosure",
            url=url,
            source_type="web_fetch",
            published_at=date(2026, 1, 1),
            content="publisher body",
        )


class ResearcherSearchBudgetTests(unittest.TestCase):
    def test_financial_disclosure_short_circuits_redundant_web_fetch(
        self,
    ) -> None:
        class ExhaustedFetchProvider(CountingSearchProvider):
            def fetch(self, url: str) -> Source:
                raise ToolExecutionError(
                    ToolErrorKind.BUDGET_EXCEEDED,
                    "web fetch lane exhausted",
                )

        class Disclosure:
            def search(self, *_args: object, **_kwargs: object) -> list[Source]:
                return [
                    Source(
                        id="annual-report",
                        title="贵州茅台 2025 年年度报告",
                        url="https://cninfo.test/600519.pdf",
                        source_type="disclosure_pdf",
                        published_at=date(2026, 4, 16),
                        content="营业收入 168838102514.79 元",
                        source_tier="primary",
                    )
                ]

        provider = ExhaustedFetchProvider()
        researcher = ResearcherAgent(
            search_tool=provider,
            fetch_tool=provider,
            disclosure_source=Disclosure(),
            max_searches_per_run=20,
            as_of=date(2026, 7, 26),
        )
        sub_question = SubQuestion(
            id="finance",
            question="贵州茅台（600519）2025 年财务指标",
            search_queries=["600519 年度报告"],
            structured_data_requests=[
                StructuredDataRequest(
                    capability="financial_indicators",
                    symbol="600519",
                )
            ],
        )

        sources, records, _calls, exhausted, _decisions = (
            researcher.research_with_budget(
                sub_question,
                max_search_calls=None,
                enable_disclosure=True,
                enable_web_search=True,
                enable_web_fetch=True,
            )
        )

        self.assertFalse(exhausted)
        self.assertEqual(provider.queries, [])
        self.assertEqual(provider.fetched_urls, [])
        self.assertIn(
            "https://cninfo.test/600519.pdf",
            {item.url for item in sources},
        )
        self.assertEqual(
            [record.query for record in records],
            ["[disclosure] 600519 年度报告"],
        )

    def test_event_disclosure_does_not_short_circuit_web_research(
        self,
    ) -> None:
        class Disclosure:
            def search(self, *_args: object, **_kwargs: object) -> list[Source]:
                return [
                    Source(
                        id="event",
                        title="项目公告",
                        url="https://cninfo.test/event.pdf",
                        source_type="disclosure_pdf",
                        published_at=date(2026, 4, 16),
                        content="项目进展",
                        source_tier="primary",
                    )
                ]

        provider = CountingSearchProvider()
        researcher = ResearcherAgent(
            search_tool=provider,
            fetch_tool=provider,
            disclosure_source=Disclosure(),
            as_of=date(2026, 7, 26),
        )
        sub_question = SubQuestion(
            id="event",
            question="宁德时代（300750）项目公告与后续报道",
            search_queries=["300750 项目进展"],
        )

        sources, _records, _calls, exhausted, _decisions = (
            researcher.research_with_budget(
                sub_question,
                max_search_calls=None,
                enable_disclosure=True,
                enable_web_search=True,
                enable_web_fetch=True,
            )
        )

        self.assertFalse(exhausted)
        self.assertEqual(provider.queries, ["300750 项目进展"])
        self.assertEqual(provider.fetched_urls, ["https://example.com/1"])
        self.assertEqual(
            {item.url for item in sources},
            {
                "https://cninfo.test/event.pdf",
                "https://example.com/1",
            },
        )

    def test_selected_fetch_hydrates_results_and_consumes_branch_budget(
        self,
    ) -> None:
        provider = CountingSearchProvider()
        researcher = ResearcherAgent(
            search_tool=provider,
            fetch_tool=provider,
            max_searches_per_run=10,
        )
        sub_question = SubQuestion(
            id="finance",
            question="年度报告核验",
            search_queries=["q1"],
        )

        sources, records, calls, exhausted, decisions = (
            researcher.research_with_budget(
                sub_question,
                max_search_calls=2,
                enable_web_fetch=True,
            )
        )

        self.assertEqual(provider.fetched_urls, ["https://example.com/1"])
        self.assertEqual(calls, 2)
        self.assertFalse(exhausted)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(sources[0].content, "publisher body")
        self.assertEqual(records[-1].query, "[web_fetch] https://example.com/1")

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

    def test_non_live_provider_does_not_consume_search_budget(self) -> None:
        provider = CountingSearchProvider()
        provider.search_counts_toward_budget = False
        researcher = ResearcherAgent(search_tool=provider, max_searches_per_run=1)
        sub_question = SubQuestion(
            id="sq1",
            question="question",
            search_queries=["q1", "q2", "q3"],
        )

        _sources, records = researcher.research(sub_question)

        self.assertEqual(provider.queries, ["q1", "q2", "q3"])
        self.assertTrue(all(not record.query.startswith("[search_limit_exceeded]") for record in records))


if __name__ == "__main__":
    unittest.main()
