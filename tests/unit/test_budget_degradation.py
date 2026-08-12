"""R119: an exhausted external budget must not discard the work already done.

R113's Q03 and Q05 delivered zero sources and zero evidence with
``terminal_failure = "run-wide web fetch request budget exhausted for
tavily_search: 20/20"``. Six searches and twenty fetches had already been spent
when the twenty-first was refused; the exception unwound the graph, so nothing
those branches had collected reached `research_join`. Ten of the twelve gold
facts the golden set never saw belong to those two questions.

The gate on degrading rather than raising used to be branch-local
`authority_returned`. It is now decided at the parallel join: an exhausted
branch degrades when any sibling produced research output, while aggregate zero
output keeps the established replayable run-level budget termination.
"""

from __future__ import annotations

import unittest

from deepresearch_agent.agents.researcher import ResearcherAgent
from deepresearch_agent.schemas import Source, SubQuestion
from deepresearch_agent.tools.contracts import ToolErrorKind
from deepresearch_agent.tools.reliable_execution import ToolExecutionError


def _source(index: int) -> Source:
    return Source(
        id=f"src-{index}",
        title=f"source {index}",
        url=f"https://example.invalid/{index}",
        source_type="web",
        content="body",
    )


class _BudgetedProvider:
    """Search succeeds; fetch refuses once the budget is spent."""

    #: The run quota is only consulted for providers that declare they count,
    #: so a stub that does not set this never exercises it.
    search_counts_toward_budget = True

    def __init__(self, *, fetch_allowance: int, search_allowance: int = 10) -> None:
        self.fetch_allowance = fetch_allowance
        self.search_allowance = search_allowance
        self.searches = 0
        self.fetches = 0

    def search(
        self,
        query: str,
        top_k: int = 1,
        context: object = None,
        **_kwargs: object,
    ) -> list[Source]:
        if self.searches >= self.search_allowance:
            raise ToolExecutionError(
                ToolErrorKind.BUDGET_EXCEEDED,
                "run-wide web search request budget exhausted for stub: 0/0",
            )
        self.searches += 1
        return [_source(self.searches)]

    def fetch(self, url: str, context: object = None, **_kwargs: object) -> Source | None:
        if self.fetches >= self.fetch_allowance:
            raise ToolExecutionError(
                ToolErrorKind.BUDGET_EXCEEDED,
                "run-wide web fetch request budget exhausted for stub: 20/20",
            )
        self.fetches += 1
        return _source(1000 + self.fetches)


class FetchBudgetDegradationTests(unittest.TestCase):
    def _research(self, provider: _BudgetedProvider) -> tuple:
        return ResearcherAgent(
            search_tool=provider,
            fetch_tool=provider,
            max_searches_per_run=10,
        ).research_with_budget(
            SubQuestion(
                id="q1",
                question="业绩",
                search_queries=["query one", "query two"],
            ),
            max_search_calls=5,
            enable_web_fetch=True,
        )

    def test_an_exhausted_fetch_budget_keeps_the_sources_already_found(self) -> None:
        """The Q03/Q05 shape: sources collected, then the fetch cap refuses."""

        sources, records, _calls, exhausted, _decisions = self._research(
            _BudgetedProvider(fetch_allowance=0)
        )

        self.assertTrue(sources, "sources collected before the refusal were discarded")
        self.assertTrue(exhausted)
        self.assertTrue(
            any("budget_exceeded" in record.query for record in records),
            "the refusal must be recorded, not swallowed",
        )

    def test_a_budget_that_refuses_this_branch_preserves_parallel_join(self) -> None:
        """Branch-local emptiness cannot prove the whole parallel run is empty."""

        sources, records, _calls, exhausted, _decisions = self._research(
            _BudgetedProvider(fetch_allowance=0, search_allowance=0)
        )

        self.assertEqual(sources, [])
        self.assertTrue(exhausted)
        self.assertTrue(any("external_search_budget_exceeded" in row.query for row in records))

    def test_reintroducing_empty_branch_raise_fails_parallel_degradation(self) -> None:
        """Mutation: the pre-R163 branch-local termination must be observable."""

        original = ResearcherAgent.research_with_budget

        def terminates_empty(self_: ResearcherAgent, *args: object, **kwargs: object) -> tuple:
            result = original(self_, *args, **kwargs)  # type: ignore[arg-type]
            if not result[0] and result[3]:
                raise ToolExecutionError(
                    ToolErrorKind.BUDGET_EXCEEDED, "empty branch unwound parallel join"
                )
            return result

        try:
            ResearcherAgent.research_with_budget = terminates_empty  # type: ignore[method-assign]
            with self.assertRaises(ToolExecutionError):
                self._research(_BudgetedProvider(fetch_allowance=0, search_allowance=0))
        finally:
            ResearcherAgent.research_with_budget = original  # type: ignore[method-assign]

    def test_restoring_the_authority_gate_loses_the_sources_again(self) -> None:
        """The deliberate wrong implementation this round removed.

        `authority_returned` is False throughout a web-only branch, so gating on
        it re-raises and the caller receives nothing.
        """

        original = ResearcherAgent.research_with_budget

        def gated(self_: ResearcherAgent, *args: object, **kwargs: object) -> tuple:
            result = original(self_, *args, **kwargs)  # type: ignore[arg-type]
            sources = result[0]
            if sources and result[3]:
                raise ToolExecutionError(
                    ToolErrorKind.BUDGET_EXCEEDED, "authority gate re-raised"
                )
            return result

        try:
            ResearcherAgent.research_with_budget = gated  # type: ignore[method-assign]
            with self.assertRaises(ToolExecutionError):
                self._research(_BudgetedProvider(fetch_allowance=0))
        finally:
            ResearcherAgent.research_with_budget = original  # type: ignore[method-assign]


class SearchBudgetDegradationTests(unittest.TestCase):
    def test_an_exhausted_search_budget_keeps_earlier_results(self) -> None:
        provider = _BudgetedProvider(fetch_allowance=10, search_allowance=1)
        sources, records, _calls, exhausted, _decisions = ResearcherAgent(
            search_tool=provider,
            fetch_tool=provider,
            max_searches_per_run=10,
        ).research_with_budget(
            SubQuestion(
                id="q1",
                question="业绩",
                search_queries=["one", "two", "three"],
            ),
            max_search_calls=5,
            enable_web_fetch=False,
        )

        self.assertTrue(sources)
        self.assertTrue(exhausted)
        self.assertTrue(
            any("external_search_budget_exceeded" in record.query for record in records)
        )


if __name__ == "__main__":
    unittest.main()


class SearchQuotaDegradationTests(unittest.TestCase):
    """`max_searches_per_run` is a quota, not an exception: it must stay one."""

    def test_an_exhausted_search_quota_keeps_earlier_results(self) -> None:
        provider = _BudgetedProvider(fetch_allowance=10, search_allowance=10)
        sources, _records, calls, exhausted, _decisions = ResearcherAgent(
            search_tool=provider,
            fetch_tool=provider,
            max_searches_per_run=1,
        ).research_with_budget(
            SubQuestion(
                id="q1",
                question="业绩",
                search_queries=["one", "two", "three"],
            ),
            max_search_calls=5,
            enable_web_fetch=False,
        )

        self.assertTrue(sources, "the quota discarded the sources it had already found")
        self.assertEqual(calls, 1, "the run quota did not stop the second search")
        self.assertFalse(exhausted, "a run quota is not a branch exhaustion")
