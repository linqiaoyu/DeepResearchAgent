from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents import Evaluator, ReporterAgent
from deepresearch_agent.agents.researcher import ResearcherAgent
from deepresearch_agent.schemas import (
    Evidence,
    NumericFields,
    ReportClaim,
    ReportDraft,
    ResearchPlan,
    ResearchState,
    StructuredDataRequest,
    StructuredDataRecord,
    SubQuestion,
)


class ReporterFinanceTemplateTests(unittest.TestCase):
    def test_report_includes_disclaimer_as_of_and_numeric_context(self) -> None:
        state = ResearchState(topic="宁德时代业绩研究")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(id="finance", question="宁德时代 2024 年业绩如何？", search_queries=["宁德时代 业绩"])
            ],
        )
        state.evidence_store = [
            Evidence(
                id="e1",
                research_id=state.research_id,
                sub_question_id="finance",
                claim="宁德时代 2024 年累计归母净利润为 507.45 亿元。",
                claim_type="data",
                source_url="https://example.com/catl",
                source_title="CATL",
                source_pub_date=date(2026, 4, 20),
                extract_text="宁德时代 2024 年累计归母净利润为 507.45 亿元。",
                numeric_fields=NumericFields(
                    entity="宁德时代",
                    metric_name="归母净利润",
                    period="20241231",
                    dimension="累计",
                    value=50_745_000_000,
                    unit="元",
                ),
            )
        ]

        report = ReporterAgent().report(state)

        self.assertIn("免责声明：本报告为研究性输出，不构成投资建议。", report)
        self.assertIn("数据截至：2026-04-20", report)
        self.assertIn("报告期/时点: 20241231", report)
        self.assertIn("口径: 累计", report)
        self.assertIn("单位: 元", report)

    def test_three_requested_metrics_with_two_covered_names_the_gap(self) -> None:
        state = ResearchState(topic="贵州茅台 2025 年财务指标")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question="营业收入、归母净利润与主营业务毛利率是多少？",
                    search_queries=["600519 年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600519",
                            periods=["20251231", "20241231"],
                            metrics=[
                                "营业收入",
                                "归母净利润",
                                "主营业务毛利率",
                            ],
                        )
                    ],
                )
            ],
        )
        state.completed_tasks = ["finance"]
        state.evidence_store = [
            self._metric_evidence(
                state,
                "revenue-2025",
                "营业收入",
                "20251231",
                168_838_102_514.79,
                61,
            ),
            self._metric_evidence(
                state,
                "revenue-2024",
                "营业收入",
                "20241231",
                170_899_152_276.34,
                61,
            ),
            self._metric_evidence(
                state,
                "profit-2025",
                "归母净利润",
                "20251231",
                82_320_067_101.68,
                62,
            ),
            self._metric_evidence(
                state,
                "profit-2024",
                "归母净利润",
                "20241231",
                86_228_146_421.62,
                62,
            ),
        ]

        report = ReporterAgent().report(state)

        self.assertIn("## 指标覆盖状态", report)
        self.assertIn("营业收入（请求报告期：2024, 2025）", report)
        self.assertIn("年报 p61", report)
        self.assertIn("归母净利润（请求报告期：2024, 2025）", report)
        self.assertIn("年报 p62", report)
        self.assertIn(
            "主营业务毛利率（请求报告期：2024, 2025）：已检索，"
            "但未获得可引用的完整指标证据",
            report,
        )
        coverage = state.metadata["requested_metric_coverage"]
        self.assertEqual(
            {
                item["metric"]: item["status"]
                for item in coverage
            },
            {
                "营业收入": "cited",
                "归母净利润": "cited",
                "主营业务毛利率": "searched_unavailable",
            },
        )

    def test_pdf_margin_header_closes_main_business_margin_requirement(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年主营业务毛利率")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question="主营业务毛利率是多少？",
                    search_queries=["600519 年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600519",
                            periods=["20251231"],
                            metrics=["主营业务毛利率"],
                        )
                    ],
                )
            ],
        )
        state.completed_tasks = ["finance"]
        state.evidence_store = [
            self._metric_evidence(
                state,
                "margin-2025",
                "毛利率",
                "20251231",
                91.23,
                10,
                unit="%",
            )
        ]

        report = ReporterAgent().report(state)

        self.assertIn("主营业务毛利率（请求报告期：2025）", report)
        self.assertIn("年报 p10", report)
        self.assertEqual(
            state.metadata["requested_metric_coverage"][0]["status"],
            "cited",
        )

    def test_current_period_without_prior_or_yoy_is_explicitly_incomplete(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年营收及同比")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question="2025 年营业收入及同比",
                    search_queries=["600519 年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600519",
                            periods=["20251231", "20241231"],
                            metrics=["营业收入"],
                        )
                    ],
                )
            ],
        )
        state.completed_tasks = ["finance"]
        state.evidence_store = [
            self._metric_evidence(
                state,
                "revenue-2025",
                "营业收入",
                "20251231",
                168_838_102_514.79,
                61,
            )
        ]

        report = ReporterAgent().report(state)
        coverage = state.metadata["requested_metric_coverage"][0]

        self.assertEqual(coverage["status"], "searched_unavailable")
        self.assertEqual(coverage["missing_periods"], ["2024"])
        self.assertIn("已取得部分证据", report)
        self.assertIn("缺失报告期：2024", report)

    def test_current_period_with_explicit_yoy_closes_comparison(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年毛利率及同比")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question="2025 年主营业务毛利率及同比",
                    search_queries=["600519 年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600519",
                            periods=["20251231", "20241231"],
                            metrics=["主营业务毛利率"],
                        )
                    ],
                )
            ],
        )
        state.completed_tasks = ["finance"]
        evidence = self._metric_evidence(
            state,
            "margin-2025-yoy",
            "毛利率",
            "20251231",
            91.23,
            10,
            unit="%",
        )
        evidence.claim = (
            "2025 年主营业务毛利率为 91.23%，同比减少 0.78 个百分点。"
        )
        evidence.extract_text = evidence.claim
        state.evidence_store = [evidence]

        ReporterAgent().report(state)
        coverage = state.metadata["requested_metric_coverage"][0]

        self.assertEqual(coverage["status"], "cited")
        self.assertTrue(coverage["comparison_observed"])
        self.assertEqual(coverage["missing_periods"], ["2024"])

    def test_financial_untyped_sections_cannot_emit_uncited_numbers(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年营业收入")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question=state.topic,
                    search_queries=["600519 年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600519",
                            periods=["20251231"],
                            metrics=["营业收入"],
                        )
                    ],
                )
            ],
        )
        evidence = self._metric_evidence(
            state,
            "revenue-2025",
            "营业收入",
            "20251231",
            168_838_102_514.79,
            61,
        )
        state.evidence_store = [evidence]
        draft = ReportDraft(
            summary="2025 年营业收入为 16883.81 亿元。",
            key_findings=[
                ReportClaim(
                    text=(
                        "2025 年营业收入为 "
                        "168,838,102,514.79 元。"
                    ),
                    evidence_ids=[evidence.id],
                )
            ],
            detailed_analysis=[],
            risks=["营业收入同比下降 1.21%。"],
            unverified_assumptions=[],
        )

        report, _invalid, _backfills = (
            ReporterAgent()._render_llm_report(state, draft)
        )

        summary = report.split("## 摘要", 1)[1].split(
            "## 关键发现",
            1,
        )[0]
        risks = report.split("## 风险与限制", 1)[1].split(
            "## 未验证假设",
            1,
        )[0]
        self.assertNotIn("16883.81", summary)
        self.assertIn("具体数值、同比变化与出处", summary)
        self.assertNotIn("1.21%", risks)
        self.assertIn("已降级为定性提示", risks)
        self.assertIn(
            "168,838,102,514.79元。 [^1]",
            report,
        )

    def test_large_structured_value_stays_exact_and_evaluates_cleanly(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年营业收入")
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question=state.topic,
                    search_queries=["600519 年度报告"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600519",
                            periods=["20251231"],
                            metrics=["营业收入"],
                        )
                    ],
                )
            ],
        )
        state.completed_tasks = ["finance"]
        evidence = ResearcherAgent()._evidence_from_record(
            state.research_id,
            "finance",
            StructuredDataRecord(
                entity="贵州茅台",
                symbol="600519",
                metric_name="营业收入",
                period="20251231",
                dimension="合并",
                value=168_838_102_514.79,
                unit="元",
                data_source="live structured provider",
                as_of=date(2026, 4, 16),
            ),
        )
        state.evidence_store = [evidence]

        state.final_report = ReporterAgent().report(state)
        result = Evaluator().evaluate(state)

        self.assertNotIn("e+", state.final_report.lower())
        self.assertIn("168838102514.79元", state.final_report)
        self.assertEqual(result.task_success_rate, 1.0)
        self.assertNotIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

    def _metric_evidence(
        self,
        state: ResearchState,
        evidence_id: str,
        metric: str,
        period: str,
        value: float,
        page: int,
        *,
        unit: str = "元",
    ) -> Evidence:
        claim = f"贵州茅台 {period} {metric}为 {value} 元。"
        return Evidence(
            id=evidence_id,
            research_id=state.research_id,
            sub_question_id="finance",
            claim=claim,
            claim_type="data",
            source_url="https://static.cninfo.com.cn/600519.pdf",
            source_title="贵州茅台 2025 年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=page,
            extract_text=claim,
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name=metric,
                period=period,
                dimension="合并",
                value=value,
                unit=unit,
            ),
            source_tier="primary",
        )


if __name__ == "__main__":
    unittest.main()
