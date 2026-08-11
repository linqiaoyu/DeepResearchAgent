from __future__ import annotations

import unittest

from pydantic import ValidationError

from deepresearch_agent.agents import ReporterAgent
from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.reporting.reader_reach import (
    evidence_the_reader_can_follow,
    orphaned_sub_questions,
)
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

    def test_selected_evidence_is_delivered_after_report_compaction(self) -> None:
        state = self._state()
        state.report_evidence_selections = ReporterAgent._select_report_evidence(
            state,
            context_evidence=[],
        )
        footnotes = build_footnote_maps(state.evidence_store)
        state.report_footnote_evidence = {
            number: item.id
            for number, item in footnotes.footnote_to_evidence.items()
        }
        original = "# report\n\n## 参考来源\n"

        report = ReporterAgent()._enforce_selected_evidence_coverage(
            original,
            state,
            footnotes.evidence_id_to_footnote,
        )

        selected = set(state.report_evidence_selections[0].evidence_ids)
        self.assertLessEqual(selected, evidence_the_reader_can_follow(state, report))
        self.assertEqual(orphaned_sub_questions(state, report), [])
        self.assertLess(report.index("## 选择证据补充"), report.index("## 参考来源"))


if __name__ == "__main__":
    unittest.main()
