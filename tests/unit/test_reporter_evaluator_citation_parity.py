from __future__ import annotations

import re
import unittest
from datetime import date

from deepresearch_agent.agents import Evaluator, ReporterAgent
from deepresearch_agent.schemas import Evidence, ResearchPlan, ResearchState, SubQuestion

CITATION_RE = re.compile(r"\[\^(\d+)\]")
REFERENCE_RE = re.compile(r"^\[\^(\d+)\]:", re.MULTILINE)


class ReporterEvaluatorCitationParityTests(unittest.TestCase):
    def test_duplicate_evidence_citations_share_reporter_footnote_and_evaluator_score(self) -> None:
        duplicate_claim = "Advisor productivity improved 18% after AI triage."
        duplicate_url = "https://example.com/advisor-ai"
        state = ResearchState(
            research_id="research-parity",
            topic="wealth AI citation parity",
            plan=ResearchPlan(
                topic="wealth AI citation parity",
                depth_level=2,
                sub_questions=[
                    SubQuestion(
                        id="sq-productivity",
                        question="How does AI affect advisor productivity?",
                        search_queries=["advisor AI productivity"],
                    ),
                    SubQuestion(
                        id="sq-risk",
                        question="What operational risks need review?",
                        search_queries=["advisor AI operational risk"],
                    ),
                ],
            ),
        )
        state.evidence_store = [
            Evidence(
                id="evidence-duplicate-a",
                research_id=state.research_id,
                sub_question_id="sq-productivity",
                claim=duplicate_claim,
                claim_type="data",
                source_url=duplicate_url,
                source_title="Advisor AI Study",
                source_pub_date=date(2026, 1, 3),
                extract_text=duplicate_claim,
            ),
            Evidence(
                id="evidence-duplicate-b",
                research_id=state.research_id,
                sub_question_id="sq-risk",
                claim=duplicate_claim,
                claim_type="data",
                source_url=duplicate_url,
                source_title="Advisor AI Study",
                source_pub_date=date(2026, 1, 3),
                extract_text=duplicate_claim,
            ),
            Evidence(
                id="evidence-risk",
                research_id=state.research_id,
                sub_question_id="sq-risk",
                claim="Human review reduced mistaken outreach escalations.",
                claim_type="fact",
                source_url="https://example.com/human-review",
                source_title="Human Review Controls",
                source_pub_date=date(2026, 1, 4),
                extract_text="Human review reduced mistaken outreach escalations.",
            ),
        ]

        report = ReporterAgent().report(state)
        state.final_report = report
        result = Evaluator().evaluate(state)

        duplicate_bullets = [
            line for line in report.splitlines() if line.startswith(f"- {duplicate_claim} ")
        ]
        duplicate_citation_numbers = {
            int(match)
            for line in duplicate_bullets
            for match in CITATION_RE.findall(line)
        }
        self.assertGreaterEqual(len(duplicate_bullets), 2)
        self.assertEqual(duplicate_citation_numbers, {1})

        reference_lines = [line for line in report.splitlines() if line.startswith("[^")]
        duplicate_reference_lines = [line for line in reference_lines if duplicate_url in line]
        self.assertEqual(len(duplicate_reference_lines), 1)

        reference_numbers = {int(match) for match in REFERENCE_RE.findall(report)}
        emitted_bullet_numbers = {
            int(match)
            for line in report.splitlines()
            if line.startswith("- ")
            for match in CITATION_RE.findall(line)
        }
        self.assertTrue(emitted_bullet_numbers)
        self.assertLessEqual(emitted_bullet_numbers, reference_numbers)

        self.assertEqual(result.citation_accuracy, 1.0)
        self.assertNotIn("citation_error", result.bad_case_categories)


if __name__ == "__main__":
    unittest.main()
