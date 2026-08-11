from __future__ import annotations

import unittest

from pydantic import ValidationError

from deepresearch_agent.agents import ReporterAgent
from deepresearch_agent.schemas import (
    Evidence,
    ReportEvidenceSelection,
    ResearchPlan,
    ResearchState,
    SubQuestion,
)


class ReportEvidenceSelectionTests(unittest.TestCase):
    def _state(self) -> ResearchState:
        state = ResearchState(
            research_id="selection-run",
            topic="evidence selection",
            plan=ResearchPlan(
                topic="evidence selection",
                sub_questions=[
                    SubQuestion(id="with", question="With?", search_queries=[]),
                    SubQuestion(id="without", question="Without?", search_queries=[]),
                ],
            ),
        )
        state.evidence_store = [
            Evidence(
                id=f"e-{index}",
                research_id=state.research_id,
                sub_question_id="with",
                claim=f"Claim {index}",
                claim_type="fact",
                source_url=f"https://example.test/{index}",
                source_title=f"Source {index}",
                extract_text=f"Claim {index}",
            )
            for index in range(1, 4)
        ]
        return state

    def test_reporter_decides_every_sub_question_before_writing(self) -> None:
        state = self._state()

        ReporterAgent().report(state, context_evidence=[state.evidence_store[1]])

        by_id = {item.sub_question_id: item for item in state.report_evidence_selections}
        self.assertEqual(set(by_id), {"with", "without"})
        self.assertEqual(by_id["with"].status, "selected")
        self.assertEqual(by_id["with"].evidence_ids, ["e-2"])
        self.assertEqual(by_id["with"].delivery_mode, "reporter_context")
        self.assertEqual(by_id["without"].status, "degraded")
        self.assertEqual(by_id["without"].evidence_ids, [])
        self.assertEqual(by_id["without"].reason, "no_evidence_for_sub_question")

    def test_context_omission_routes_bounded_selection_to_mechanical_floor(self) -> None:
        state = self._state()

        ReporterAgent().report(state, context_evidence=[])

        selected = state.report_evidence_selections[0]
        self.assertEqual(selected.delivery_mode, "mechanical_floor")
        self.assertEqual(selected.evidence_ids, ["e-1", "e-2"])

    def test_selection_schema_rejects_degraded_claim_with_evidence(self) -> None:
        with self.assertRaises(ValidationError):
            ReportEvidenceSelection(
                sub_question_id="with",
                status="degraded",
                evidence_ids=["e-1"],
                delivery_mode="none",
                reason="contradiction",
            )


if __name__ == "__main__":
    unittest.main()
