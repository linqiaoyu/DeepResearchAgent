"""R124: a refinement with nothing to name is not issued.

R121 gave the loop a working second pass, and R121's live run showed what it
spent that pass on. Four of Q13's six refined queries were

    研究主体 事项 公告
    研究主体 事项 报告

-- placeholder, placeholder, document type. No entity, no metric, no period.
They were sent to a live search engine, spent the branch budget R121 had just
rationed for the second iteration, and returned nothing, which is why that
iteration retrieved no additional gold fact.

The placeholder was deliberate: `build_replan_query` refuses to fall back to the
sub-question's prose, so a plan with no structured request assembles a query
from no fields. Keeping the query "visibly low-specificity" was the intent; the
query was still issued. A field assembly with no fields is an absent query.
"""

from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.orchestration.research_loop import (
    ReplanQueryUnavailable,
    ResearchSufficiency,
    SubquestionSufficiency,
    build_replan_query,
    refine_research_plan,
)
from deepresearch_agent.schemas import (
    ResearchPlan,
    ResearchState,
    StructuredDataRequest,
    SubQuestion,
)


class _Policy:
    def document_type_for_direction(self, direction: str) -> str:
        return "公告"

    def metric_gap_direction(self) -> str:
        return "指标补充"

    def evidence_gap_direction(self) -> str:
        return "证据补充"


def _bare(identifier: str) -> SubQuestion:
    """No structured request and no planner terms to borrow either."""

    return SubQuestion(
        id=identifier, question="该主体的相关情况如何？", search_queries=["研究"]
    )


def _planner_terms(identifier: str) -> SubQuestion:
    """No structured request, but the planner left usable terms."""

    return SubQuestion(
        id=identifier,
        question="该主体的相关情况如何？",
        search_queries=["示例公司 装机量 2024"],
    )


def _structured(identifier: str) -> SubQuestion:
    return SubQuestion(
        id=identifier,
        question="该主体的营业收入是多少？",
        search_queries=["q"],
        structured_data_requests=[
            StructuredDataRequest(
                capability="financial_indicators",
                symbol="600519",
                company_name="示例公司",
                metrics=["营业收入"],
                periods=["20241231"],
            )
        ],
    )


class BuildReplanQueryTests(unittest.TestCase):
    def test_a_sub_question_with_no_fields_yields_no_query(self) -> None:
        with self.assertRaises(ReplanQueryUnavailable):
            build_replan_query(_bare("sq"), "公告")

    def test_the_placeholder_query_is_no_longer_reachable(self) -> None:
        try:
            query = build_replan_query(_bare("sq"), "公告")
        except ReplanQueryUnavailable:
            return
        self.fail(f"placeholder query still issued: {query!r}")

    def test_planner_terms_are_borrowed_when_there_is_no_structured_request(
        self,
    ) -> None:
        query = build_replan_query(_planner_terms("sq"), "公告")
        self.assertIn("示例公司", query)
        self.assertNotIn("研究主体", query)

    def test_a_structured_sub_question_still_builds_a_query(self) -> None:
        query = build_replan_query(_structured("sq"), "公告")
        self.assertIn("600519", query)
        self.assertIn("营业收入", query)
        self.assertNotIn("研究主体", query)
        self.assertNotIn("事项", query)


class RefineResearchPlanTests(unittest.TestCase):
    def _refine(self, sub_questions: list[SubQuestion]) -> dict[str, list[str]]:
        state = ResearchState(topic="t")
        state.plan = ResearchPlan(topic="t", sub_questions=sub_questions)
        sufficiency = ResearchSufficiency(
            score=0.1,
            sufficient=False,
            by_sub_question=[
                SubquestionSufficiency(
                    sub_question_id=item.id,
                    evidence_count=0,
                    independent_source_domains=0,
                    average_confidence=0.0,
                    unresolved_critic_issues=0,
                    missing_counterargument=True,
                    sufficient=False,
                    gaps=["evidence_count", "counterargument"],
                )
                for item in sub_questions
            ],
        )
        return refine_research_plan(
            state,
            sufficiency,
            as_of=date(2026, 7, 9),
            iteration=1,
            domain_pack=_Policy(),
        )

    def test_no_placeholder_query_survives_refinement(self) -> None:
        refined = self._refine([_bare("a"), _structured("b")])
        every = [query for queries in refined.values() for query in queries]
        self.assertTrue(every, "refinement produced nothing at all")
        for query in every:
            self.assertNotIn("研究主体", query)
            self.assertNotIn("事项 公告", query)

    def test_the_structured_sub_question_still_gets_refined(self) -> None:
        refined = self._refine([_bare("a"), _structured("b")])
        self.assertTrue(refined.get("b"), f"structured branch lost its queries: {refined}")

    def test_a_branch_that_cannot_be_assembled_gets_no_queries(self) -> None:
        refined = self._refine([_bare("a")])
        self.assertEqual(refined.get("a", []), [])

    def test_the_refusal_is_recorded_in_the_decision(self) -> None:
        state = ResearchState(topic="t")
        state.plan = ResearchPlan(topic="t", sub_questions=[_bare("a")])
        sufficiency = ResearchSufficiency(
            score=0.1,
            sufficient=False,
            by_sub_question=[
                SubquestionSufficiency(
                    sub_question_id="a",
                    evidence_count=0,
                    independent_source_domains=0,
                    average_confidence=0.0,
                    unresolved_critic_issues=0,
                    missing_counterargument=True,
                    sufficient=False,
                    gaps=["evidence_count"],
                )
            ],
        )
        refine_research_plan(
            state,
            sufficiency,
            as_of=date(2026, 7, 9),
            iteration=1,
            domain_pack=_Policy(),
        )
        outcomes = [
            item.outcome
            for item in state.agent_decisions
            if item.decision_type == "research_replan"
        ]
        self.assertTrue(
            any("unassemblable" in str(item) for item in outcomes),
            f"the dropped refinement left no trace: {outcomes}",
        )


if __name__ == "__main__":
    unittest.main()
