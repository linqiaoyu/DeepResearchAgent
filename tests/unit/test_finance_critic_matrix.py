from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents import CriticAgent
from deepresearch_agent.schemas import Evidence, NumericFields, ResearchState


class FinanceCriticMatrixTests(unittest.TestCase):
    def _state(self, evidence: list[Evidence]) -> ResearchState:
        state = ResearchState(topic="宁德时代业绩与扩张研究")
        state.evidence_store = evidence
        return state

    def _data(
        self,
        evidence_id: str,
        claim: str,
        value: float,
        metric_name: str = "归母净利润",
        period: str = "20241231",
        dimension: str = "累计",
        source_kind: str = "text",
    ) -> Evidence:
        return Evidence(
            id=evidence_id,
            research_id="matrix",
            sub_question_id="finance",
            claim=claim,
            claim_type="data",
            source_kind=source_kind,
            source_url=f"https://example.com/{evidence_id}",
            source_title=evidence_id,
            source_pub_date=date(2026, 4, 20),
            extract_text=claim,
            numeric_fields=NumericFields(
                entity="宁德时代",
                metric_name=metric_name,
                period=period,
                dimension=dimension,
                value=value,
                unit="元",
            ),
        )

    def test_false_conflict_attributable_profit_and_net_profit_do_not_trigger(self) -> None:
        report = CriticAgent().critique(
            self._state(
                [
                    self._data("a", "宁德时代 2024 年累计归母净利润为 507.45 亿元。", 50_745_000_000),
                    self._data(
                        "b",
                        "宁德时代 2024 年累计净利润为 520.00 亿元。",
                        52_000_000_000,
                        metric_name="净利润",
                    ),
                ]
            )
        )

        self.assertNotIn("numeric_conflict", {issue.issue_type for issue in report.issues})

    def test_false_conflict_single_quarter_and_cumulative_do_not_trigger(self) -> None:
        report = CriticAgent().critique(
            self._state(
                [
                    self._data("a", "宁德时代 2024 年累计归母净利润为 507.45 亿元。", 50_745_000_000),
                    self._data(
                        "b",
                        "宁德时代 2024 年单季归母净利润为 105.10 亿元。",
                        10_510_000_000,
                        dimension="单季",
                    ),
                ]
            )
        )

        self.assertNotIn("numeric_conflict", {issue.issue_type for issue in report.issues})

    def test_true_conflict_same_four_key_text_sources_triggers_numeric_conflict(self) -> None:
        report = CriticAgent().critique(
            self._state(
                [
                    self._data("a", "宁德时代 2024 年累计归母净利润为 507.45 亿元。", 50_745_000_000),
                    self._data("b", "宁德时代 2024 年累计归母净利润为 410.00 亿元。", 41_000_000_000),
                ]
            )
        )

        self.assertIn("numeric_conflict", {issue.issue_type for issue in report.issues})

    def test_true_conflict_text_vs_structured_source_is_high_and_labeled(self) -> None:
        report = CriticAgent().critique(
            self._state(
                [
                    self._data("text", "宁德时代 2024 年累计归母净利润为 410.00 亿元。", 41_000_000_000),
                    self._data(
                        "structured",
                        "宁德时代 2024 年累计归母净利润为 507.45 亿元。",
                        50_745_000_000,
                        source_kind="structured",
                    ),
                ]
            )
        )
        conflicts = [issue for issue in report.issues if issue.issue_type == "numeric_conflict"]

        self.assertEqual(conflicts[0].severity, "high")
        self.assertIn("structured official data source", conflicts[0].message)

    def test_temporal_conflict_same_event_different_dates_triggers(self) -> None:
        report = CriticAgent().critique(
            self._state(
                [
                    Evidence(
                        id="date-a",
                        research_id="matrix",
                        sub_question_id="expansion",
                        claim="宁德时代欧洲工厂投产日期为2025年6月。",
                        claim_type="fact",
                        source_url="https://example.com/date-a",
                        source_title="date-a",
                        source_pub_date=date(2026, 3, 5),
                        extract_text="宁德时代欧洲工厂投产日期为2025年6月。",
                    ),
                    Evidence(
                        id="date-b",
                        research_id="matrix",
                        sub_question_id="expansion",
                        claim="宁德时代欧洲工厂投产日期为2025年9月。",
                        claim_type="fact",
                        source_url="https://example.com/date-b",
                        source_title="date-b",
                        source_pub_date=date(2026, 3, 6),
                        extract_text="宁德时代欧洲工厂投产日期为2025年9月。",
                    ),
                ]
            )
        )

        self.assertIn("temporal_conflict", {issue.issue_type for issue in report.issues})


if __name__ == "__main__":
    unittest.main()
