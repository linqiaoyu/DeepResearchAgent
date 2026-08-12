from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from deepresearch_agent.agents import ReporterAgent
from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.evaluation.behavioral import refute_premise_verdict
from deepresearch_agent.schemas import (
    Evidence,
    ReportEvidenceSelection,
    ReportClaim,
    ReportDraft,
    ResearchPlan,
    ResearchState,
    SubQuestion,
)
from deepresearch_agent.settings import project_root


class PremiseReportingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        questions = json.loads(
            (project_root() / "data/golden_set/v1/questions.json").read_text(encoding="utf-8")
        )["questions"]
        cls.gold = {item["id"]: item["gold"] for item in questions}

    def _r160_q16(self) -> tuple[ResearchState, str]:
        raw = json.loads(
            (
                project_root()
                / "tests/fixtures/behavioral/r160_live_q16_premise_input.json"
            ).read_text(encoding="utf-8")
        )
        state = ResearchState(topic=raw["topic"])
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                claim_type="fact",
                extract_text=item["claim"],
                **item,
            )
            for item in raw["evidence"]
        ]
        state.report_evidence_selections = [
            ReportEvidenceSelection(
                sub_question_id="premise",
                status="selected",
                evidence_ids=[item.id for item in state.evidence_store],
                delivery_mode="reporter_context",
                reason="reduced_real_r160_selection",
            )
        ]
        return state, raw["failing_report_excerpt"]

    def _repair(self, state: ResearchState, report: str) -> str:
        agent = ReporterAgent(domain_pack=load_domain_pack("finance"))
        assessment = agent.domain_pack.assess_premise(
            state.topic, state.evidence_store, state.report_evidence_selections
        )
        ref_map = build_footnote_maps(state.evidence_store).evidence_id_to_footnote
        return agent._enforce_premise_assessment(report, assessment, ref_map)

    def test_real_r160_q16_failure_is_repaired_from_selected_evidence(self) -> None:
        state, before = self._r160_q16()
        after = self._repair(state, before)

        self.assertFalse(refute_premise_verdict(before, self.gold["Q16"]).satisfied)
        self.assertTrue(refute_premise_verdict(after, self.gold["Q16"]).satisfied)
        self.assertIn("## 前提核验", after)
        self.assertNotIn("主要源于比亚迪垂直整合", after)

    def test_true_or_inconclusive_topic_does_not_get_a_refutation(self) -> None:
        evidence = Evidence(
            id="e-1",
            research_id="r",
            sub_question_id="sq",
            claim="甲公司2024年位列全球第一。",
            claim_type="fact",
            source_url="https://example.test/one",
            source_title="source",
            extract_text="甲公司2024年位列全球第一。",
        )
        selection = ReportEvidenceSelection(
            sub_question_id="sq",
            status="selected",
            evidence_ids=[evidence.id],
            delivery_mode="reporter_context",
            reason="test",
        )

        assessment = load_domain_pack("finance").assess_premise(
            "研究甲公司2024年的全球排名。", [evidence], [selection]
        )

        self.assertEqual(assessment.status, "unresolved")
        self.assertEqual(
            ReporterAgent(domain_pack=load_domain_pack("finance"))._enforce_premise_assessment(
                "# 报告\n\n## 摘要\n甲公司位列第一。", assessment, {"e-1": 1}
            ),
            "# 报告\n\n## 摘要\n甲公司位列第一。",
        )

    def test_prompt_payload_carries_selected_evidence_only(self) -> None:
        state, _ = self._r160_q16()
        assessment = load_domain_pack("finance").assess_premise(
            state.topic, state.evidence_store, state.report_evidence_selections
        )
        selected = {
            evidence_id
            for selection in state.report_evidence_selections
            for evidence_id in selection.evidence_ids
        }

        self.assertEqual(assessment.status, "contradicted")
        self.assertTrue(set(assessment.evidence_ids) <= selected)

    def test_reporter_prompt_and_output_enforce_the_assessment(self) -> None:
        state, _ = self._r160_q16()
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(id="reasons", question="原因？", search_queries=[]),
                SubQuestion(id="market_share", question="排名？", search_queries=[]),
            ],
        )

        class Completion:
            def __init__(self) -> None:
                self.payload: dict[str, object] = {}

            def complete(self, **kwargs: object) -> SimpleNamespace:
                messages = kwargs["messages"]
                assert isinstance(messages, list)
                self.payload = json.loads(messages[1]["content"])
                return SimpleNamespace(
                    parsed=ReportDraft(
                        summary="宁德时代已被比亚迪反超，主要源于成本优势。",
                        key_findings=[
                            ReportClaim(
                                text="宁德时代被比亚迪反超的关键驱动是成本。",
                                evidence_ids=[state.evidence_store[0].id],
                            )
                        ],
                    ),
                    repair_attempts=0,
                )

        completion = Completion()
        report = ReporterAgent(
            llm_client=completion,  # type: ignore[arg-type]
            domain_pack=load_domain_pack("finance"),
        ).report(state, context_evidence=state.evidence_store)

        assessment = completion.payload["premise_assessment"]
        self.assertIsInstance(assessment, dict)
        self.assertEqual(assessment["status"], "contradicted")
        self.assertNotIn("关键驱动是成本", report)
        self.assertTrue(refute_premise_verdict(report, self.gold["Q16"]).satisfied)


if __name__ == "__main__":
    unittest.main()
