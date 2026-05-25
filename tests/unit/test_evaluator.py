from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents import Evaluator
from deepresearch_agent.schemas import CriticReport, Evidence, Issue, ResearchState


class EvaluatorTests(unittest.TestCase):
    def _state_with_supported_report(self) -> ResearchState:
        state = ResearchState(topic="wealth AI")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Advisor productivity improved 18%. [^1]\n\n[^1]: A"
        return state

    def _critic_issue(self, index: int) -> Issue:
        return Issue(
            issue_type="missing_citation",
            severity="medium",
            affected_claims=["Advisor productivity improved 18%."],
            message=f"Missing citation issue {index}.",
        )

    def test_citation_accuracy_is_one_when_claim_is_supported_by_evidence(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Advisor productivity improved 18%. [^1]\n\n[^1]: A"
        result = Evaluator().evaluate(state)
        self.assertEqual(result.citation_accuracy, 1.0)
        self.assertEqual(result.task_success_rate, 1.0)

    def test_citation_accuracy_drops_when_existing_citation_does_not_support_claim(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Assets under management doubled in one quarter. [^1]\n\n[^1]: A"

        result = Evaluator().evaluate(state)

        self.assertLess(result.citation_accuracy, 1.0)
        self.assertEqual(result.bad_case_categories["citation_error"], 1)

    def test_invalid_citation_marker_counts_as_citation_error(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Advisor productivity improved 18%. [^2]\n\n[^1]: A"

        result = Evaluator().evaluate(state)

        self.assertEqual(result.citation_accuracy, 0.0)
        self.assertEqual(result.bad_case_categories["citation_error"], 1)

    def test_critic_issue_types_are_propagated_to_bad_case_categories(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Advisor productivity improved 18%. [^1]\n\n[^1]: A"
        state.critic_report = CriticReport(
            passed=False,
            overall_quality=0.4,
            issues=[
                Issue(
                    issue_type="numeric_conflict",
                    severity="high",
                    affected_claims=["Advisor productivity improved 18%."],
                    message="Conflicting productivity figures were found.",
                ),
                Issue(
                    issue_type="numeric_conflict",
                    severity="medium",
                    affected_claims=["Advisor productivity improved 18%."],
                    message="A second numeric conflict should increment the same category.",
                ),
                Issue(
                    issue_type="outdated_source",
                    severity="medium",
                    affected_claims=["Advisor productivity improved 18%."],
                    message="The supporting source is too old for this claim.",
                ),
            ],
        )

        result = Evaluator().evaluate(state)

        self.assertEqual(result.citation_accuracy, 1.0)
        self.assertEqual(result.bad_case_categories["numeric_conflict"], 2)
        self.assertEqual(result.bad_case_categories["outdated_source"], 1)
        self.assertNotIn("citation_error", result.bad_case_categories)

    def test_critic_catch_rate_matches_issue_count_heuristic(self) -> None:
        cases = [
            ("without_critic_report", None, 1.0),
            ("with_empty_critic_report", 0, 1.0),
            ("with_one_issue", 1, 0.333),
            ("with_three_issues", 3, 1.0),
            ("with_four_issues", 4, 1.0),
        ]

        for name, issue_count, expected in cases:
            with self.subTest(name=name):
                state = self._state_with_supported_report()
                if issue_count is not None:
                    state.critic_report = CriticReport(
                        passed=issue_count == 0,
                        overall_quality=1.0 if issue_count == 0 else 0.4,
                        issues=[self._critic_issue(index) for index in range(issue_count)],
                    )

                result = Evaluator().evaluate(state)

                self.assertEqual(result.critic_catch_rate, expected)


if __name__ == "__main__":
    unittest.main()
