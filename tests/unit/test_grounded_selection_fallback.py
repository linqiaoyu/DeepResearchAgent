"""R107: a guard rejection must redirect the selection, not delete the metric.

R105's first A-share run reported `营业收入：未取得可引用的原始披露事实` in
`关键发现` while the same report's coverage section quoted both years from
AKShare records the renderer held all along. The renderer picked the two
annual-report PDF extracts because `source_tier="primary"` outranks being
typed, and each of those extracts was a bare digit string naming no metric, so
the fidelity guard could not tell what the number measured. One selection, no
retry: the guard's correct refusal cost the reader a fact the run had.

The evidence below reproduces that shape from the archived run
(`artifacts/105/live-moutai-fixed`): same tiers, same kinds, same values, same
bare-digit extracts.
"""

from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents.reporter import ReporterAgent
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.schemas import (
    Evidence,
    NumericFields,
    ResearchPlan,
    ResearchState,
    StructuredDataRecord,
    StructuredDataRequest,
    SubQuestion,
)

REVENUE_2024 = "174,144,069,958.25"
REVENUE_2023 = "150,560,330,316.45"
PDF_2024 = "170,899,152,276.34"
PDF_2023 = "147,693,604,994.14"


class _MoutaiFixture:
    """The archived R105 evidence shape, shared by both test classes."""

    def _key_findings(self, report: str) -> str:
        lines = report.splitlines()
        start = lines.index("## 关键发现")
        end = next(
            (
                index
                for index in range(start + 1, len(lines))
                if lines[index].startswith("## ")
            ),
            len(lines),
        )
        return "\n".join(lines[start:end])

    def _renderer(self):
        # The composition boundary, not the concrete class: the core stays free
        # of a direct finance import.
        return load_domain_pack("finance").grounded_fact_renderer()

    def _reporter(self) -> ReporterAgent:
        return ReporterAgent(grounded_fact_renderer=self._renderer())

    def _report(self) -> str:
        return "\n".join(
            [
                "# 报告",
                "",
                "## 关键发现",
                "- 营业收入两年均有增长。 [^1]",
                "",
                "## 参考来源",
                "[^1]: AKShare 600519 2024",
            ]
        )

    def _ref_map(self, state: ResearchState) -> dict[str, int]:
        return {
            evidence.id: index
            for index, evidence in enumerate(state.evidence_store, start=1)
        }

    def _state(self) -> ResearchState:
        state = ResearchState(
            topic="贵州茅台（600519）2023 与 2024 年营业收入的变化"
        )
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="fin_compare",
                    question="营业收入两年如何变化？",
                    search_queries=["600519 年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600519",
                            periods=["20231231", "20241231"],
                            metrics=["营业收入"],
                        )
                    ],
                )
            ],
        )
        state.completed_tasks = ["fin_compare"]
        state.evidence_store = [
            self._structured(state, "structured-2023", "20231231", REVENUE_2023),
            self._structured(state, "structured-2024", "20241231", REVENUE_2024),
            self._bare_digit_pdf(state, "pdf-2023", "2023", PDF_2023),
            self._bare_digit_pdf(state, "pdf-2024", "2024", PDF_2024),
        ]
        return state

    def _structured(
        self,
        state: ResearchState,
        evidence_id: str,
        period: str,
        value: str,
    ) -> Evidence:
        plain = value.replace(",", "")
        return Evidence(
            id=evidence_id,
            research_id=state.research_id,
            sub_question_id="fin_compare",
            claim=f"600519 {period} 累计营业收入为{plain}元。",
            claim_type="data",
            source_kind="structured",
            source_url=f"akshare://营业收入/600519/{period}",
            source_title="AKShare: stock_financial_abstract 600519 营业收入",
            extract_text=f"600519|营业收入|{period}|累计|{plain}|元",
            # The archived run recorded AKShare records at `unknown`, which is
            # what puts them below any primary extract in the ranking.
            source_tier="unknown",
            structured_record=StructuredDataRecord(
                entity="600519",
                symbol="600519",
                metric_name="营业收入",
                period=period,
                dimension="累计",
                value=plain,
                unit="元",
                data_source="AKShare: stock_financial_abstract",
                as_of=date(2026, 8, 9),
            ),
            numeric_fields=NumericFields(
                entity="600519",
                metric_name="营业收入",
                period=period,
                dimension="累计",
                value=plain,
                unit="元",
            ),
        )

    def _bare_digit_pdf(
        self,
        state: ResearchState,
        evidence_id: str,
        period: str,
        value: str,
    ) -> Evidence:
        return Evidence(
            id=evidence_id,
            research_id=state.research_id,
            sub_question_id="fin_compare",
            claim=f"{period}年营业收入为{value}元",
            claim_type="data",
            source_kind="text",
            source_url="https://static.cninfo.com.cn/finalpage/600519.PDF",
            source_title="贵州茅台年度报告",
            source_page=6,
            # The excerpt is the number and nothing else: it names no metric,
            # so no reader and no guard can tell what it measures.
            extract_text=value,
            source_tier="primary",
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="营业收入",
                period=period,
                dimension="未标注",
                value=value.replace(",", ""),
                unit="元",
            ),
        )


if __name__ == "__main__":
    unittest.main()


class GroundedSelectionFallbackTests(_MoutaiFixture, unittest.TestCase):
    def test_unverifiable_top_ranked_extract_does_not_cost_the_reader_the_metric(
        self,
    ) -> None:
        state = self._state()

        guarded = self._reporter()._enforce_reader_fidelity(
            self._report(),
            state,
            self._ref_map(state),
        )

        findings = self._key_findings(guarded)
        self.assertNotIn("未取得可引用的原始披露事实", findings)
        self.assertIn(f"{REVENUE_2024} 元", findings)
        self.assertIn(f"{REVENUE_2023} 元", findings)

    def test_reader_gets_the_filed_figure_not_the_unverifiable_one(self) -> None:
        state = self._state()

        guarded = self._reporter()._enforce_reader_fidelity(
            self._report(),
            state,
            self._ref_map(state),
        )

        findings = self._key_findings(guarded)
        # The bare-digit PDF extracts name no metric, so nothing in the run can
        # confirm what they measure. They must not reach the reader as the
        # answer just because their source outranks the records that can --
        # and the reader must get the figure that does verify in their place,
        # which is what makes dropping the metric a failure here too.
        self.assertNotIn(PDF_2024, findings)
        self.assertNotIn(PDF_2023, findings)
        self.assertIn(f"{REVENUE_2024} 元", findings)
        self.assertIn(f"{REVENUE_2023} 元", findings)

    def test_both_requested_periods_survive_the_retry(self) -> None:
        batch = self._renderer().render(self._state())

        self.assertEqual(batch.gaps, ())
        self.assertEqual(len(batch.claims), 1)
        claim = batch.claims[0]
        self.assertEqual(len(claim.evidence_ids), 2)
        self.assertIn("同比增长15.66%", claim.text)

    def test_verifiable_top_ranked_evidence_is_still_preferred(self) -> None:
        """The retry must not demote a primary source that does verify."""
        state = self._state()
        for evidence in state.evidence_store:
            if evidence.source_tier == "primary":
                # Give the PDF extracts the metric name they lacked; they now
                # ground their own numbers and must win on tier as before.
                evidence.extract_text = (
                    f"营业收入 {evidence.numeric_fields.period}年 "
                    f"{evidence.extract_text}元"
                )

        batch = self._renderer().render(state)

        self.assertEqual(len(batch.claims), 1)
        self.assertIn(PDF_2024, batch.claims[0].text)
        self.assertIn(PDF_2023, batch.claims[0].text)

    def test_metric_stays_a_gap_when_no_selection_verifies(self) -> None:
        """Fail-closed is unchanged: no verifiable option is still a gap."""
        state = self._state()
        state.evidence_store = [
            evidence
            for evidence in state.evidence_store
            if evidence.source_tier == "primary"
        ]

        batch = self._renderer().render(state)
        reporter = self._reporter()
        guarded = reporter._enforce_reader_fidelity(
            self._report(),
            state,
            self._ref_map(state),
        )

        self.assertEqual(len(batch.claims), 1)
        self.assertIn("未取得可引用的原始披露事实", self._key_findings(guarded))
        self.assertEqual(
            reporter.last_stats["reader_fidelity_guard"]["grounded_gaps"],
            ["营业收入"],
        )


class DegradationNoticeRepetitionTests(_MoutaiFixture, unittest.TestCase):
    """R107: the reader is told once that a line was removed, not once per line."""

    NOTICE = (
        "该数值表述未通过 Evidence 保真守卫，无法由引用证据核验，"
        "已移除；请参阅关键发现中的可核验数值。"
    )

    def test_repeated_downgrades_state_the_reason_once(self) -> None:
        state = self._state()
        report = "\n".join(
            [
                "# 报告",
                "",
                "## 关键发现",
                "- 营业收入两年均有增长。 [^1]",
                "",
                "## 详细分析",
                "- 2024年营业收入为999,999,999,999.99元。 [^3]",
                "- 2023年营业收入为888,888,888,888.88元。 [^3]",
                "- 收入增长的驱动因素在现有证据中没有数据。 [^3]",
                "",
                "## 参考来源",
                "[^1]: AKShare 600519",
            ]
        )

        reporter = self._reporter()
        guarded = reporter._enforce_reader_fidelity(
            report,
            state,
            self._ref_map(state),
        )

        self.assertEqual(
            reporter.last_stats["reader_fidelity_guard"]["downgraded_numeric_lines"],
            2,
        )
        self.assertEqual(guarded.count(self.NOTICE), 1)
        # The unverifiable figures are gone; the line with no numbers stays.
        self.assertNotIn("999,999,999,999.99", guarded)
        self.assertNotIn("888,888,888,888.88", guarded)
        self.assertIn("收入增长的驱动因素", guarded)
