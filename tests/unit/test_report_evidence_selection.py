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
    NumericFields,
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
        state.report_evidence_selections = ReporterAgent()._select_report_evidence(
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

    def test_selection_preserves_two_subject_numeric_matrix(self) -> None:
        question = SubQuestion(
            id="compare",
            question="比较甲公司与乙公司2024年金额和份额",
            search_queries=[],
        )
        evidence = []
        for index, (entity, unit, value) in enumerate(
            (("甲公司", "亿元", "10"), ("甲公司", "%", "20"),
             ("乙公司", "亿元", "30"), ("乙公司", "%", "40"))
        ):
            evidence.append(
                Evidence(
                    id=f"matrix-{index}", research_id="r", sub_question_id="compare",
                    claim=f"{entity}2024年为{value}{unit}", claim_type="data",
                    source_url=f"https://example.test/matrix/{index}", source_title="s",
                    extract_text="x", numeric_fields=NumericFields(
                        entity=entity, metric_name="指标", period="2024",
                        value=value, unit=unit,
                    ),
                )
            )
        selected = ReporterAgent()._bounded_evidence_selection(question, evidence)
        self.assertEqual(
            {(item.numeric_fields.entity, item.numeric_fields.unit) for item in selected},
            {("甲公司", "亿元"), ("甲公司", "%"), ("乙公司", "亿元"), ("乙公司", "%")},
        )

    def test_selected_rate_must_be_visible_not_only_its_source(self) -> None:
        item = Evidence(
            id="rate", research_id="r", sub_question_id="compare",
            claim="甲公司2024年收入10亿元，同比增长20%。", claim_type="data",
            source_url="https://example.test/rate", source_title="s", extract_text="x",
            numeric_fields=NumericFields(
                entity="甲公司", metric_name="收入", period="2024",
                value="10", unit="亿元",
            ),
        )
        self.assertFalse(
            ReporterAgent._selected_numeric_evidence_visible(
                item, "## 发现\n甲公司2024年收入10亿元。 [^1]\n"
            )
        )
        self.assertTrue(
            ReporterAgent._selected_numeric_evidence_visible(
                item, "## 发现\n甲公司2024年收入10亿元，同比增长20%。 [^1]\n"
            )
        )


if __name__ == "__main__":
    unittest.main()
