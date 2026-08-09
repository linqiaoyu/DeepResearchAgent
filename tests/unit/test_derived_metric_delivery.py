"""R102: a metric no source publishes is still answerable from its components."""

from __future__ import annotations

import re
import unittest
from datetime import date
from decimal import Decimal

from deepresearch_agent.agents import ReporterAgent
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

FINANCE = load_domain_pack("finance")
TOPIC = "蔚来 2023 与 2024 年营收和毛利率的变化及其驱动因素"

# The filer's own Company Facts, CNY, 20-F/FY, fetched while writing this test.
FILED = {
    "20231231": {"营业收入": Decimal("55617933000"), "毛利": Decimal("3051796000")},
    "20241231": {"营业收入": Decimal("65731559000"), "毛利": Decimal("6492762000")},
}


class ComponentRequestTests(unittest.TestCase):
    def test_the_plan_asks_for_what_the_ratio_is_made_of(self) -> None:
        """R101's report named the derivation and did not perform it.

        `主营业务毛利率` is listed as unsupported by the SEC provider, and requests
        were built from the words in the question, so nothing ever asked for
        `毛利` -- the one input the filer publishes for every period it reports.
        """

        plan = FINANCE.deterministic_plan(TOPIC, 2)
        assert plan is not None
        requested = {
            metric
            for sub_question in plan.sub_questions
            for request in sub_question.structured_data_requests
            if request.capability == "financial_indicators"
            for metric in request.metrics
        }

        self.assertIn("毛利", requested)
        self.assertIn("营业收入", requested)
        # Appended, not substituted: a source that publishes the metric directly
        # must still be asked for it.
        self.assertIn("主营业务毛利率", requested)


class DerivedMetricDeliveryTests(unittest.TestCase):
    def _state(self) -> ResearchState:
        state = ResearchState(topic=TOPIC)
        state.plan = ResearchPlan(
            topic=TOPIC,
            sub_questions=[
                SubQuestion(
                    id="financial_metrics",
                    question=TOPIC,
                    search_queries=["fixture"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            company_name="NIO Inc.",
                            metrics=["营业收入", "主营业务毛利率"],
                            periods=["20231231", "20241231"],
                        )
                    ],
                )
            ],
        )
        state.evidence_store = [
            Evidence(
                id=f"{metric}-{period}",
                research_id=state.research_id,
                sub_question_id="financial_metrics",
                claim=f"NIO Inc. {period} {metric} {value}",
                claim_type="data",
                source_url="https://www.sec.gov/cgi-bin/browse-edgar?CIK=1736541",
                source_title="SEC EDGAR Company Facts",
                source_pub_date=date(2025, 4, 8),
                extract_text=f"NIO Inc. {period} {metric} {value}",
                source_tier="primary",
                # A real run populates both: the record is the provider's answer,
                # the fields are what the reader-facing metric machinery reads.
                numeric_fields=NumericFields(
                    entity="NIO Inc.",
                    metric_name=metric,
                    period=period,
                    dimension="合计",
                    value=value,
                    unit="CNY",
                ),
                structured_record=StructuredDataRecord(
                    entity="NIO Inc.",
                    symbol="NIO",
                    metric_name=metric,
                    period=period,
                    dimension="合计",
                    value=value,
                    unit="CNY",
                    data_source="SEC EDGAR Company Facts",
                    as_of=date(2025, 4, 8),
                ),
            )
            for period, values in FILED.items()
            for metric, value in values.items()
        ]
        return state

    def test_both_periods_reach_the_reader_with_their_arithmetic(self) -> None:
        """The reader gets a number, what it was computed from, and where it came from."""

        state = self._state()
        reporter = ReporterAgent(
            grounded_fact_renderer=FINANCE.grounded_fact_renderer(),
            numeric_citation_policy=FINANCE.numeric_citation_policy(),
            domain_pack=FINANCE,
        )

        report = reporter.report(state)

        self.assertIn("## 派生指标", report)
        section = report.split("## 派生指标", 1)[1].split("\n## ", 1)[0]
        lines = [line for line in section.splitlines() if line.strip().startswith("- ")]

        self.assertEqual(len(lines), 2, f"one line per period, got: {lines}")
        # 3,051,796,000 / 55,617,933,000 and 6,492,762,000 / 65,731,559,000
        self.assertIn("5.49%", section)
        self.assertIn("9.88%", section)
        for line in lines:
            self.assertIn("推导值", line)
            self.assertIn("/", line, "a derived value must show what it divides")
            self.assertRegex(line, r"\[\^\d+\]", "a derived value must cite its inputs")
            citations = re.findall(r"\[\^(\d+)\]", line)
            self.assertEqual(
                citations,
                list(dict.fromkeys(citations)),
                f"the same footnote is printed twice: {line}",
            )

    def test_a_period_missing_one_input_is_not_derived(self) -> None:
        """Half an identity is not a derivation."""

        state = self._state()
        state.evidence_store = [
            item for item in state.evidence_store if item.id != "毛利-20231231"
        ]

        derived = FINANCE.reader_derived_metrics(state.evidence_store)

        self.assertEqual([item["period"] for item in derived], ["20241231"])

    def test_periods_are_never_crossed(self) -> None:
        """R102: the old pairing ignored the period and could divide across years."""

        state = self._state()
        derived = {item["period"]: item for item in FINANCE.reader_derived_metrics(state.evidence_store)}

        self.assertEqual(derived["20231231"]["value"], "5.49%")
        self.assertEqual(derived["20241231"]["value"], "9.88%")


if __name__ == "__main__":
    unittest.main()


class NoSelfContradictionTests(DerivedMetricDeliveryTests):
    """R103: a report must not state a gap in the section that fills it."""

    def test_the_gap_notice_points_at_the_derivation_it_performed(self) -> None:
        """R102 shipped `本轮未作推算` two lines above the 推算.

        The metric is still not directly disclosed, so it is still reported as a
        gap. What must not survive is telling the reader the computation was not
        done while printing its result below.
        """

        reporter = ReporterAgent(
            grounded_fact_renderer=FINANCE.grounded_fact_renderer(),
            numeric_citation_policy=FINANCE.numeric_citation_policy(),
            domain_pack=FINANCE,
        )

        report = reporter.report(self._state())

        self.assertIn("## 派生指标", report)
        self.assertNotIn(
            "本轮未作推算",
            report,
            "the report states a gap in the same breath as the value that fills it",
        )
        self.assertIn("推导值见「派生指标」", report)
        # Both sections that carry gap wording must agree.
        for section in ("关键发现", "指标覆盖状态"):
            if f"## {section}" not in report:
                continue
            body = report.split(f"## {section}", 1)[1].split("\n## ", 1)[0]
            if "主营业务毛利率" in body:
                self.assertNotIn("本轮未作推算", body)

    def test_a_metric_with_no_derivation_still_reports_the_gap_plainly(self) -> None:
        """The notice must not claim a derivation that did not happen."""

        state = self._state()
        state.evidence_store = [
            item for item in state.evidence_store if not item.id.startswith("毛利")
        ]
        reporter = ReporterAgent(
            grounded_fact_renderer=FINANCE.grounded_fact_renderer(),
            numeric_citation_policy=FINANCE.numeric_citation_policy(),
            domain_pack=FINANCE,
        )

        report = reporter.report(state)

        self.assertNotIn("## 派生指标", report)
        self.assertIn("本轮未作推算", report)
