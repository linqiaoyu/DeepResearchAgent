"""R108: a question asking 毛利率 gets 毛利率, from the field the source publishes.

Every R107 live run ended with `主营业务毛利率：未在可用的结构化年报字段中找到该
指标`. The topic said 毛利率; `planning._METRIC_TERMS` escalated it into
`主营业务毛利率`, a stricter ratio no A-share source publishes and one
`evidence_matches_metric` correctly refuses to satisfy with a bare 毛利率
record. The fallback component `毛利` does not exist in AKShare either, so the
metric was structurally unanswerable -- while `stock_financial_abstract`
publishes 毛利率 directly for both issuers R107 tested.

Values below are AKShare's, read from `stock_financial_abstract` for 002594
while writing this test.
"""

from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.metric_coverage import evaluate_metric_coverage
from deepresearch_agent.schemas import (
    Evidence,
    ResearchState,
    StructuredDataRecord,
)

FINANCE = load_domain_pack("finance")
TOPIC = "比亚迪（002594）2023 与 2024 年营业收入和毛利率的变化及其驱动因素"
STRICT_TOPIC = "比亚迪（002594）2024 年主营业务毛利率"
MARGIN = {"20231231": "20.21483", "20241231": "19.43834"}
REVENUE = {"20231231": "602315354000", "20241231": "777102455000"}


class MarginIsAnsweredTests(unittest.TestCase):
    def test_the_plan_asks_for_the_metric_the_question_names(self) -> None:
        plan = FINANCE.deterministic_plan(TOPIC, 1)
        assert plan is not None
        requested = {
            metric
            for sub_question in plan.sub_questions
            for request in sub_question.structured_data_requests
            if request.capability == "financial_indicators"
            for metric in request.metrics
        }

        self.assertIn("毛利率", requested)
        self.assertNotIn("主营业务毛利率", requested)

    def test_an_explicit_main_business_question_still_asks_for_it(self) -> None:
        """Only the stricter question gets the stricter metric."""
        plan = FINANCE.deterministic_plan(STRICT_TOPIC, 1)
        assert plan is not None
        requested = {
            metric
            for sub_question in plan.sub_questions
            for request in sub_question.structured_data_requests
            if request.capability == "financial_indicators"
            for metric in request.metrics
        }

        self.assertIn("主营业务毛利率", requested)

    def test_the_reader_gets_the_margin_not_a_gap(self) -> None:
        batch = FINANCE.grounded_fact_renderer().render(self._state())

        self.assertEqual(batch.gaps, ())
        margin = self._claim(batch, "毛利率")
        self.assertIn("19.43834%", margin.text)
        self.assertIn("20.21483%", margin.text)

    def test_a_rate_moves_in_points_not_in_percent(self) -> None:
        """20.21% to 19.44% is a fall of 0.78 points, not of 3.84%."""
        batch = FINANCE.grounded_fact_renderer().render(self._state())

        margin = self._claim(batch, "毛利率")
        self.assertIn("同比下降0.78个百分点", margin.text)
        self.assertNotIn("同比下降3.84%", margin.text)

    def test_an_amount_still_moves_in_percent(self) -> None:
        batch = FINANCE.grounded_fact_renderer().render(self._state())

        revenue = self._claim(batch, "营业收入")
        self.assertIn("同比增长29.02%", revenue.text)
        self.assertNotIn("个百分点", revenue.text)

    def test_a_percent_is_written_tight_to_its_figure(self) -> None:
        batch = FINANCE.grounded_fact_renderer().render(self._state())

        margin = self._claim(batch, "毛利率")
        self.assertNotIn("19.43834 %", margin.text)

    def test_a_bare_margin_record_still_cannot_answer_main_business(self) -> None:
        """The R100 protection is untouched: 口径 is what qualifies a record."""
        matches = FINANCE.evidence_matches_metric

        state = self._state()
        bare = next(
            item
            for item in state.evidence_store
            if item.structured_record.metric_name == "毛利率"
        )

        self.assertTrue(matches(bare, "毛利率"))
        self.assertFalse(matches(bare, "主营业务毛利率"))

    def test_a_main_business_dimension_still_answers_main_business(self) -> None:
        """A filing's own 酒类毛利率 row must keep closing the strict metric."""
        matches = FINANCE.evidence_matches_metric

        state = self._state()
        scoped = next(
            item
            for item in state.evidence_store
            if item.structured_record.metric_name == "毛利率"
        )
        scoped.structured_record.dimension = "酒类"

        self.assertTrue(matches(scoped, "主营业务毛利率"))

    def test_coverage_reports_the_margin_as_cited(self) -> None:
        statuses = {
            item.metric: item.status
            for item in evaluate_metric_coverage(self._state(), FINANCE)
        }

        self.assertEqual(statuses.get("毛利率"), "cited")
        self.assertEqual(statuses.get("营业收入"), "cited")

    def _claim(self, batch, label: str):
        return next(claim for claim in batch.claims if claim.label == label)

    def _state(self) -> ResearchState:
        state = ResearchState(topic=TOPIC)
        state.plan = FINANCE.deterministic_plan(TOPIC, 1)
        assert state.plan is not None
        sub_question_id = state.plan.sub_questions[0].id
        state.completed_tasks = [sq.id for sq in state.plan.sub_questions]
        state.evidence_store = [
            self._record(state, sub_question_id, "营业收入", period, value, "元")
            for period, value in REVENUE.items()
        ] + [
            self._record(state, sub_question_id, "毛利率", period, value, "%")
            for period, value in MARGIN.items()
        ]
        return state

    def _record(
        self,
        state: ResearchState,
        sub_question_id: str,
        metric: str,
        period: str,
        value: str,
        unit: str,
    ) -> Evidence:
        return Evidence(
            id=f"{metric}-{period}",
            research_id=state.research_id,
            sub_question_id=sub_question_id,
            claim=f"002594 {period} 累计{metric}为{value}{unit}。",
            claim_type="data",
            source_kind="structured",
            source_url=f"akshare://{metric}/002594/{period}",
            source_title="AKShare: stock_financial_abstract 002594",
            extract_text=f"002594|{metric}|{period}|累计|{value}|{unit}",
            source_tier="unknown",
            structured_record=StructuredDataRecord(
                entity="002594",
                symbol="002594",
                metric_name=metric,
                period=period,
                dimension="累计",
                value=value,
                unit=unit,
                data_source="AKShare: stock_financial_abstract",
                as_of=date(2026, 8, 9),
            ),
        )


if __name__ == "__main__":
    unittest.main()


class TotalRevenueIsRequestableTests(unittest.TestCase):
    """R109: `"营业收入" in "营业总收入"` is False, and the planner used substrings.

    Golden Q01 asks for 营业总收入. The planner requested only 归母净利润, so the
    metric had no reader-facing slot; the filing text sat in evidence quoting
    `年度内公司实现营业总收入 1,741.44 亿元，同比增长 15.66%` while the report
    said the fact was unavailable. The provider vocabulary has canonicalised
    this row since AKShare 1.18.64; only planning had not.
    """

    TOPIC = (
        "解读贵州茅台2024年度业绩：营业总收入、归母净利润及各自同比增速，"
        "以及茅台酒与系列酒的收入结构。"
    )

    def _metrics(self, topic: str) -> set[str]:
        plan = FINANCE.deterministic_plan(topic, 1)
        assert plan is not None
        return {
            metric
            for sub_question in plan.sub_questions
            for request in sub_question.structured_data_requests
            if request.capability == "financial_indicators"
            for metric in request.metrics
        }

    def test_a_total_revenue_question_requests_revenue(self) -> None:
        self.assertIn("营业收入", self._metrics(self.TOPIC))

    def test_it_still_requests_the_other_named_metric(self) -> None:
        self.assertIn("归母净利润", self._metrics(self.TOPIC))

    def test_the_plain_form_is_unaffected(self) -> None:
        self.assertIn(
            "营业收入", self._metrics("贵州茅台2024年营业收入和归母净利润")
        )

    def test_the_substring_trap_is_stated(self) -> None:
        """The reason this was missed, kept where it can be read."""
        self.assertNotIn("营业收入", "营业总收入"[:3])
        self.assertFalse("营业收入" in "营业总收入")
