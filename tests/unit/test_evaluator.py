from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents import Evaluator
from deepresearch_agent.schemas import CriticReport, Evidence, Issue, ResearchState


class EvaluatorTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
