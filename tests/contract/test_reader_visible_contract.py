from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from deepresearch_agent.agents import ReporterAgent, ResearcherAgent
from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.reporting.report_assembly import append_degradation_notice
from deepresearch_agent.schemas import (
    ResearchPlan,
    ResearchState,
    Source,
    StructuredDataRecord,
    StructuredDataRequest,
    SubQuestion,
)
from scripts.check_reader_visible_contract import (
    ExpectedFinding,
    section,
    validate_degradation_notice,
    validate_expected_findings,
    validate_footnotes,
    validate_self_consistency,
)


class ReaderVisibleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = load_domain_pack("finance")
        self.state = ResearchState(topic="蔚来 2024 年年报的营收与毛利情况")
        self.state.plan = ResearchPlan(
            topic=self.state.topic,
            sub_questions=[
                SubQuestion(
                    id="revenue",
                    question=self.state.topic,
                    search_queries=["NIO 2024 annual report revenue gross profit"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="NIO",
                            periods=["2024"],
                            metrics=["营业收入", "毛利"],
                        )
                    ],
                )
            ],
        )
        researcher = ResearcherAgent(domain_pack=self.pack)
        self.state.evidence_store = [
            researcher._evidence_from_record(
                self.state.research_id,
                "revenue",
                self._record("营业收入", Decimal("65731559000")),
            ),
            researcher._evidence_from_record(
                self.state.research_id,
                "revenue",
                self._record("毛利", Decimal("6492762000")),
            ),
        ]
        self.state.completed_tasks = ["revenue"]

    def test_c1_c2_key_findings_complete_and_self_consistent(self) -> None:
        reporter = ReporterAgent(
            grounded_fact_renderer=self.pack.grounded_fact_renderer(),
            domain_pack=self.pack,
        )

        report = reporter.report(self.state)

        expected = (
            ExpectedFinding("营业收入", "65,731,559,000 CNY"),
            ExpectedFinding("毛利", "6,492,762,000 CNY"),
        )
        validate_expected_findings(report, expected)
        validate_self_consistency(report, ("营业收入", "毛利"))
        self.assertNotIn("未取得", section(report, "关键发现"))

    def test_c3_duplicate_urls_share_one_footnote_without_misrefs(self) -> None:
        maps = build_footnote_maps(self.state.evidence_store)
        self.assertEqual(set(maps.evidence_id_to_footnote.values()), {1})
        self.assertEqual(len(maps.unique_refs), 1)
        report = ReporterAgent(
            grounded_fact_renderer=self.pack.grounded_fact_renderer(),
            domain_pack=self.pack,
        ).report(self.state)
        validate_footnotes(report)

    def test_c4_grouping_and_grouped_magnitude_mutation(self) -> None:
        evidence = self.state.evidence_store[0]
        supported = "营业收入：NIO Inc. 2024年营业收入为65,731,559,000 CNY。"
        grouped_but_wrong = "营业收入：NIO Inc. 2024年营业收入为6,573,155,900 CNY。"
        policy = self.pack.numeric_citation_policy()
        self.assertFalse(policy.has_numeric_mismatch(supported, [evidence]))
        self.assertTrue(policy.has_numeric_mismatch(grouped_but_wrong, [evidence]))

    def test_c5_rejection_is_reader_visible_degradation(self) -> None:
        self.state.metadata["degradation_events"] = [
            {
                "tool": "web_source_governance",
                "reason": "permanent",
                "impact": "rejected source reason=forecast_source",
                "attempts": 1,
            }
        ]
        report = append_degradation_notice("# Report", self.state)
        validate_degradation_notice(report, degradation_expected=True)
        self.assertIn("forecast_source", report)

    def test_d2_off_period_and_forecast_rejected_target_numeric_page_kept(self) -> None:
        rejected = (
            self._source(
                "NIO Inc. Reports Unaudited Fourth Quarter and Full Year 2025 Financial Results",
                "https://finance.yahoo.com/nio-full-year-2025-results",
                "2025 results",
            ),
            self._source(
                "NIO Inc. December 31, 2025",
                "https://www.sec.gov/nio-20251231x20f.htm",
                "2025 annual filing",
            ),
            self._source(
                "Nio stock price forecast",
                "https://example.com/nio-forecast",
                "forecast",
            ),
            self._source(
                "蔚来股价预测",
                "https://example.com/nio-price",
                "预测",
            ),
        )
        for source in rejected:
            with self.subTest(source=source.url):
                self.assertIsNotNone(
                    self.pack.web_source_rejection_reason(source, ("2024",))
                )
        target = self._source(
            "NIO 2024 annual report revenue",
            "https://www.sec.gov/nio-20241231x20f.htm",
            "2024 revenue was 65,731,559,000 CNY.",
        )
        self.assertIsNone(
            self.pack.web_source_rejection_reason(target, ("2024",))
        )

    def test_d2_researcher_omits_rejected_web_candidates_and_records_degradation(
        self,
    ) -> None:
        target = self._source(
            "NIO 2024 annual report revenue",
            "https://www.sec.gov/nio-20241231x20f.htm",
            "2024 revenue was 65,731,559,000 CNY.",
        )
        forecast = self._source(
            "Nio stock price forecast",
            "https://example.com/nio-forecast",
            "forecast",
        )

        class Search:
            search_counts_toward_budget = False

            def search(self, *_args: object, **_kwargs: object) -> list[Source]:
                return [forecast, target]

        researcher = ResearcherAgent(search_tool=Search(), domain_pack=self.pack)
        sources, records = researcher.research(self.state.plan.sub_questions[0])

        self.assertEqual([source.url for source in sources], [target.url])
        self.assertTrue(
            any(record.query.startswith("[web_source_rejected:") for record in records)
        )

    def test_d3_sec_companyfacts_evidence_is_primary(self) -> None:
        self.assertTrue(self.state.evidence_store)
        self.assertTrue(
            all(item.source_tier == "primary" for item in self.state.evidence_store)
        )

    @staticmethod
    def _record(metric: str, value: Decimal) -> StructuredDataRecord:
        return StructuredDataRecord(
            entity="NIO Inc.",
            symbol="CIK0001736541",
            metric_name=metric,
            period="2024-12-31",
            dimension="年度",
            value=value,
            unit="CNY",
            data_source="SEC EDGAR Company Facts",
            as_of=date(2026, 7, 1),
            source_pub_date=date(2025, 4, 8),
            source_url="https://www.sec.gov/Archives/edgar/data/1736541/filing/",
        )

    @staticmethod
    def _source(title: str, url: str, content: str) -> Source:
        return Source(
            title=title,
            url=url,
            source_type="web",
            content=content,
        )


if __name__ == "__main__":
    unittest.main()
