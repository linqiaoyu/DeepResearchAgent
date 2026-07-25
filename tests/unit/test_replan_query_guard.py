from __future__ import annotations

import re
import unittest
from datetime import date

from deepresearch_agent.orchestration.decision_context import (
    build_decision_context,
)
from deepresearch_agent.orchestration.research_loop import (
    MAX_REPLAN_QUERY_CHARS,
    ResearchSufficiency,
    SubquestionSufficiency,
    refine_research_plan,
)
from deepresearch_agent.schemas import (
    CriticReport,
    Issue,
    ResearchPlan,
    ResearchState,
    RetryTask,
    SubQuestion,
)


class ReplanQueryGuardTests(unittest.TestCase):
    def test_replan_query_excludes_audit_vocabulary_and_keeps_issue_trace(
        self,
    ) -> None:
        task = RetryTask(
            id="retry-019b",
            reason="projection confidence: low",
            query="old",
            sub_question_id="finance",
        )
        state = ResearchState(topic="宁德时代研究")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question=(
                        "宁德时代 2024 年业绩与欧洲工厂投产日期"
                        " resolve unverified_projection"
                    ),
                    search_queries=["old"],
                )
            ],
        )
        state.critic_report = CriticReport(
            passed=False,
            overall_quality=0.6,
            issues=[
                Issue(
                    issue_type="unverified_projection",
                    severity="high",
                    message=(
                        "Projection claim has low extraction confidence: "
                        "2025年6月"
                    ),
                    suggested_retry_task=task,
                )
            ],
            retry_tasks=[task],
        )
        sufficiency = ResearchSufficiency(
            score=0.5,
            sufficient=False,
            by_sub_question=[
                SubquestionSufficiency(
                    sub_question_id="finance",
                    evidence_count=1,
                    independent_source_domains=1,
                    average_confidence=0.6,
                    freshest_evidence_age_days=10,
                    unresolved_critic_issues=1,
                    missing_counterargument=False,
                    gaps=["unresolved_critic_issues"],
                    sufficient=False,
                )
            ],
        )
        context = build_decision_context(
            state,
            iteration=2,
            sufficiency=sufficiency,
        )

        refined = refine_research_plan(
            state,
            sufficiency,
            as_of=date(2026, 7, 25),
            iteration=2,
            decision_context=context,
        )

        forbidden = re.compile(
            r"resolve |unverified_|_gap|confidence:|Projection claim|"
            r"critic|issue_id|\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b",
            re.IGNORECASE,
        )
        self.assertTrue(refined["finance"])
        self.assertTrue(
            all(not forbidden.search(query) for query in refined["finance"])
        )
        self.assertTrue(
            all(
                len(query) <= MAX_REPLAN_QUERY_CHARS
                for query in refined["finance"]
            )
        )
        decision_context = state.agent_decisions[-1].inputs[
            "decision_context"
        ]
        issue = decision_context["unresolved_critic_issues"][0]
        self.assertEqual(issue["issue_id"], task.id)
        self.assertEqual(issue["issue_type"], "unverified_projection")
        self.assertIn("confidence", issue["message"])


if __name__ == "__main__":
    unittest.main()
