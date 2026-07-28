from __future__ import annotations

import unittest
from datetime import date

from deepresearch_agent.agents import Evaluator
from deepresearch_agent.schemas import (
    CriticReport,
    Evidence,
    Issue,
    NumericFields,
    ResearchPlan,
    ResearchState,
    StructuredDataRequest,
    SubQuestion,
)


class EvaluatorTests(unittest.TestCase):
    def _state_with_supported_report(self) -> ResearchState:
        state = ResearchState(topic="wealth AI")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Advisor productivity improved 18%. [^1]\n\n[^1]: A"
        state.report_footnote_evidence = {1: state.evidence_store[0].id}
        return state

    def _state_with_financial_report(self, claim: str) -> ResearchState:
        state = ResearchState(topic="贵州茅台 2025 年财务表现")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="finance",
                claim=(
                    "2025年营业收入168,838,102,514.79元，2024年"
                    "170,899,152,276.34元，同比下降1.21%；归母净利润"
                    "8,232,006.710168万元；主营业务毛利率91.23%，"
                    "同比下降0.78个百分点。"
                ),
                claim_type="data",
                source_url="https://example.com/annual-report.pdf",
                source_title="贵州茅台2025年年度报告",
                source_pub_date=date(2026, 3, 1),
                source_page=61,
                extract_text=(
                    "金额单位：元。营业收入168,838,102,514.79，"
                    "上年同期170,899,152,276.34，同比下降1.21%。"
                    "归母净利润8,232,006.710168万元。主营业务毛利率"
                    "91.23%，同比下降0.78个百分点。第61页。"
                ),
                source_tier="primary",
            )
        ]
        state.final_report = f"- {claim} [^7]\n\n[^7]: 贵州茅台2025年年度报告，p.999"
        state.report_footnote_evidence = {7: state.evidence_store[0].id}
        return state

    def _critic_issue(self, index: int) -> Issue:
        return Issue(
            issue_type="missing_citation",
            severity="medium",
            affected_claims=["Advisor productivity improved 18%."],
            message=f"Missing citation issue {index}.",
        )

    def test_citation_accuracy_is_one_when_claim_is_supported_by_evidence(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Advisor productivity improved 18%. [^1]\n\n[^1]: A"
        state.report_footnote_evidence = {1: state.evidence_store[0].id}
        result = Evaluator().evaluate(state)
        self.assertEqual(result.citation_accuracy, 1.0)
        self.assertEqual(result.task_success_rate, 1.0)

    def test_missing_typed_metric_cannot_be_counted_as_task_success(self) -> None:
        state = self._state_with_supported_report()
        state.plan = ResearchPlan(
            topic=state.topic,
            sub_questions=[
                SubQuestion(
                    id="finance",
                    question="2024 营业收入是多少？",
                    search_queries=[],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            symbol="600519",
                            periods=["2024"],
                            metrics=["营业收入"],
                        )
                    ],
                )
            ],
        )

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 0.0)
        self.assertEqual(result.bad_case_categories["required_output_incomplete"], 1)

    def test_amount_unit_is_not_normalized_as_scope(self) -> None:
        fields = NumericFields(
            entity="某公司",
            metric_name="营业收入",
            period="20241231",
            dimension="千元",
            value=362012554,
            unit="千元",
        )

        self.assertEqual(fields.dimension, "未标注")
        self.assertEqual(fields.unit, "千元")

    def test_citation_accuracy_drops_when_existing_citation_does_not_support_claim(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Assets under management doubled in one quarter. [^1]\n\n[^1]: A"
        state.report_footnote_evidence = {1: state.evidence_store[0].id}

        result = Evaluator().evaluate(state)

        self.assertLess(result.citation_accuracy, 1.0)
        self.assertEqual(result.bad_case_categories["citation_error"], 1)

    def test_financial_numeric_audit_accepts_units_rounding_and_ignores_locator_numbers(
        self,
    ) -> None:
        state = self._state_with_financial_report(
            "贵州茅台2025年营业收入1688.38亿元，2024年1708.99亿元，"
            "同比下降1.21%；归母净利润823.20亿元；主营业务毛利率"
            "91.23%，同比下降0.78个百分点，见年报p.999。"
        )

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 1.0)
        self.assertEqual(result.citation_accuracy, 1.0)
        self.assertNotIn("numeric_citation_mismatch", result.bad_case_categories)

    def test_financial_numeric_audit_rejects_030_numeric_mutations(self) -> None:
        mutations = {
            "magnitude": (
                "贵州茅台2025年营业收入16883.81亿元，2024年1708.99亿元，"
                "同比下降1.21%；归母净利润823.20亿元；主营业务毛利率"
                "91.23%，同比下降0.78个百分点。"
            ),
            "decimal": (
                "贵州茅台2025年营业收入1688.38亿元，2024年1708.99亿元，"
                "同比下降1.21%；归母净利润823.20亿元；主营业务毛利率"
                "9.123%，同比下降0.78个百分点。"
            ),
            "direction": (
                "贵州茅台2025年营业收入1688.38亿元，2024年1708.99亿元，"
                "同比增长1.21%；归母净利润823.20亿元；主营业务毛利率"
                "91.23%，同比下降0.78个百分点。"
            ),
        }

        for name, claim in mutations.items():
            with self.subTest(name=name):
                result = Evaluator().evaluate(self._state_with_financial_report(claim))

                self.assertEqual(result.task_success_rate, 0.0)
                self.assertEqual(result.citation_accuracy, 0.0)
                self.assertEqual(
                    result.bad_case_categories["numeric_citation_mismatch"],
                    1,
                )

    def test_numeric_audit_does_not_treat_extractor_claim_as_source_truth(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年营业收入")
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim="2025年营业收入为16883.81亿元。",
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="贵州茅台2025年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=61,
            extract_text="2025年营业收入为1688.381亿元。",
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="营业收入",
                period="20251231",
                dimension="合并",
                value=16883.81,
                unit="亿元",
            ),
            source_tier="primary",
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 2025年营业收入为16883.81亿元。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告 p61"
        )
        state.report_footnote_evidence = {1: evidence.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 0.0)
        self.assertEqual(result.citation_accuracy, 0.0)
        self.assertEqual(
            result.bad_case_categories["numeric_citation_mismatch"],
            1,
        )

    def test_numeric_audit_rejects_wrong_uncited_summary_amount(
        self,
    ) -> None:
        state = self._state_with_financial_report(
            "贵州茅台2025年营业收入1688.38亿元，2024年1708.99亿元，"
            "同比下降1.21%；归母净利润823.20亿元；主营业务毛利率"
            "91.23%，同比下降0.78个百分点。"
        )
        state.final_report = (
            "## 摘要\n\n"
            "贵州茅台2025年营业收入为16883.81亿元。\n\n"
            + (state.final_report or "")
        )

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 0.0)
        self.assertEqual(result.citation_accuracy, 1.0)
        self.assertEqual(
            result.bad_case_categories["numeric_citation_mismatch"],
            1,
        )

    def test_grounded_numeric_fields_can_interpret_pdf_table_rate(self) -> None:
        state = ResearchState(topic="贵州茅台 2025 年主营业务毛利率")
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim="主营业务毛利率为91.23%。",
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="贵州茅台2025年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=10,
            extract_text=(
                "分行业 营业收入 营业成本 毛利率（%）\n"
                "酒类 168774585187.65 14805900139.59 91.23"
            ),
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="毛利率",
                period="20251231",
                dimension="主营业务",
                value=91.23,
                unit="%",
            ),
            source_tier="primary",
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 主营业务毛利率为91.23%。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告 p10"
        )
        state.report_footnote_evidence = {1: evidence.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 1.0)
        self.assertEqual(result.citation_accuracy, 1.0)
        self.assertNotIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

    def test_product_margin_cannot_support_main_business_margin(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年毛利率")
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
                            metrics=["主营业务毛利率"],
                        )
                    ],
                )
            ],
        )
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim="茅台酒毛利率为93.53%。",
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="贵州茅台2025年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=10,
            extract_text=(
                "主营业务分行业 酒类 毛利率（%） 91.23\n"
                "主营业务分产品 茅台酒 毛利率（%） 93.53"
            ),
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="主营业务毛利率",
                period="20251231",
                dimension="茅台酒",
                value=93.53,
                unit="%",
            ),
            source_tier="primary",
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 主营业务毛利率为93.53%。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告 p10"
        )
        state.report_footnote_evidence = {1: evidence.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 0.0)
        self.assertIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

    def test_product_margin_yoy_cannot_support_main_business_yoy(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年毛利率及同比")
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
                            periods=["20251231", "20241231"],
                            metrics=["主营业务毛利率"],
                        )
                    ],
                )
            ],
        )
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim="茅台酒毛利率同比减少0.53个百分点。",
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="贵州茅台2025年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=10,
            extract_text=(
                "主营业务分产品情况 毛利率（%） "
                "毛利率比上年增减（%）\n"
                "茅台酒 93.53 减少 0.53 个百\n分点"
            ),
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="主营业务毛利率",
                period="20251231",
                dimension="茅台酒",
                value=93.53,
                unit="%",
            ),
            source_tier="primary",
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 主营业务毛利率同比减少0.53个百分点。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告 p10"
        )
        state.report_footnote_evidence = {1: evidence.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 0.0)
        self.assertIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

    def test_explicit_main_business_metric_accepts_generic_pdf_header(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年毛利率")
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
                            metrics=["主营业务毛利率"],
                        )
                    ],
                )
            ],
        )
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim="主营业务毛利率为91.23%。",
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="贵州茅台2025年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=10,
            extract_text=(
                "主营业务分行业情况\n"
                "分行业 营业收入 营业成本 毛利率（%）\n"
                "酒类 168,774,585,187.65 14,805,900,139.59 91.23"
            ),
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="主营业务毛利率",
                period="20251231",
                dimension="酒类",
                value=91.23,
                unit="%",
            ),
            source_tier="primary",
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 主营业务毛利率为91.23%。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告 p10"
        )
        state.report_footnote_evidence = {1: evidence.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 1.0)
        self.assertNotIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

    def test_main_business_margin_accepts_same_row_yoy_from_pdf(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年毛利率及同比")
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
                            periods=["20251231", "20241231"],
                            metrics=["主营业务毛利率"],
                        )
                    ],
                )
            ],
        )
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim="主营业务毛利率为91.23%，同比减少0.78个百分点。",
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="贵州茅台2025年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=10,
            extract_text=(
                "主营业务分行业情况\n"
                "分行业 营业收入 营业成本 毛利率（%） 营业收入比上\n"
                "年增减（%） 营业成本比上\n"
                "年增减（%） 毛利率比上年\n增减（%）\n"
                "酒类 168,774,585,187.65 14,805,900,139.59 "
                "91.23 -1.08 8.63 减少 0.78 个百\n分点\n"
                "茅台酒 146,499,906,480.49 9,484,757,825.54 "
                "93.53 0.39 9.50 减少 0.53 个百\n分点"
            ),
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="主营业务毛利率",
                period="20251231",
                dimension="酒类",
                value=91.23,
                unit="%",
            ),
            source_tier="primary",
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 主营业务毛利率为91.23%，同比减少0.78个百分点。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告 p10"
        )
        state.report_footnote_evidence = {1: evidence.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 1.0)
        self.assertNotIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

    def test_relative_yoy_does_not_support_percentage_point_backsolve(
        self,
    ) -> None:
        state = ResearchState(topic="某公司 2025 年主营业务毛利率及同比")
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim="2025年主营业务毛利率为50%，同比增长10%。",
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="某公司2025年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=10,
            extract_text="2025年主营业务毛利率为50%，同比增长10%。",
            numeric_fields=NumericFields(
                entity="某公司",
                metric_name="主营业务毛利率",
                period="20251231",
                dimension="主营业务",
                value=50,
                unit="%",
            ),
            source_tier="primary",
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 2024年主营业务毛利率为40%。 [^1]\n\n"
            "[^1]: 某公司2025年年度报告 p10"
        )
        state.report_footnote_evidence = {1: evidence.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 0.0)
        self.assertEqual(
            result.bad_case_categories["numeric_citation_mismatch"],
            1,
        )

    def test_numeric_audit_accepts_yoy_derived_from_two_report_periods(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年营业收入及同比")
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim=(
                "2025 年营业收入为 168,838,102,514.79 元，"
                "2024 年为 170,899,152,276.34 元。"
            ),
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="贵州茅台2025年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=61,
            extract_text=(
                "项目 附注 2025年度 2024年度\n"
                "一、营业总收入 172,054,171,890.91 "
                "174,144,069,958.25\n"
                "其中：营业收入 44 168,838,102,514.79 "
                "170,899,152,276.34"
            ),
            source_tier="primary",
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 2025年营业收入168,838,102,514.79元，2024年"
            "170,899,152,276.34元，同比下降1.21%。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告 p61"
        )
        state.report_footnote_evidence = {1: evidence.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 1.0)
        self.assertEqual(result.citation_accuracy, 1.0)
        self.assertNotIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

    def test_yoy_rate_binds_to_subject_year_not_comparison_base(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年营业收入及同比")
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim=(
                "营业收入 168,838,102,514.79 "
                "170,899,152,276.34 -1.21"
            ),
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="贵州茅台2025年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=6,
            extract_text=(
                "营业收入 168,838,102,514.79 "
                "170,899,152,276.34 -1.21"
            ),
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="营业收入",
                period="2025年",
                dimension="合并",
                value=168_838_102_514.79,
                unit="元",
            ),
            source_tier="primary",
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 2025年营业收入为1688.38亿元"
            "（168,838,102,514.79元），较2024年下降1.21%。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告 p6"
        )
        state.report_footnote_evidence = {1: evidence.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 0.0)
        self.assertIn("numeric_citation_mismatch", result.bad_case_categories)

    def test_comparison_base_amount_is_not_misread_as_yoy(
        self,
    ) -> None:
        state = ResearchState(
            topic="贵州茅台 2025 年营业收入及同比"
        )
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim=(
                "2025年营业收入为168,838,102,514.79元，"
                "较2024年下降1.21%。"
            ),
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="贵州茅台2025年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=6,
            extract_text=(
                "单位：元 币种：人民币\n"
                "主要会计数据 2025年 2024年 2023年\n"
                "营业收入 168,838,102,514.79 "
                "170,899,152,276.34 -1.21 "
                "147,693,604,994.14"
            ),
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="营业收入",
                period="2025年",
                dimension="年度主要会计数据",
                value=168_838_102_514.79,
                unit="元",
            ),
            source_tier="primary",
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 2025年营业收入为1,688.38亿元"
            "（168,838,102,514.79元），较2024年的"
            "1,708.99亿元下降1.21%。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告 p6"
        )
        state.report_footnote_evidence = {1: evidence.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 1.0)
        self.assertNotIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

        state.final_report = state.final_report.replace(
            "1,708.99亿元",
            "1,708.09亿元",
        )
        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 0.0)
        self.assertIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

    def test_numeric_audit_rejects_swapped_financial_statement_column(
        self,
    ) -> None:
        state = ResearchState(topic="贵州茅台 2025 年营业收入")
        evidence = Evidence(
            research_id=state.research_id,
            sub_question_id="finance",
            claim="2025 年营业收入为 170,899,152,276.34 元。",
            claim_type="data",
            source_url="https://example.com/annual-report.pdf",
            source_title="贵州茅台2025年年度报告",
            source_pub_date=date(2026, 4, 16),
            source_page=61,
            extract_text=(
                "项目 附注 2025年度 2024年度\n"
                "其中：营业收入 44 168,838,102,514.79 "
                "170,899,152,276.34"
            ),
            source_tier="primary",
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="营业收入",
                period="20251231",
                dimension="合并",
                value=170_899_152_276.34,
                unit="元",
            ),
        )
        state.evidence_store = [evidence]
        state.final_report = (
            "- 2025年营业收入170,899,152,276.34元。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告 p61"
        )
        state.report_footnote_evidence = {1: evidence.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 0.0)
        self.assertIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

    def test_invalid_citation_marker_counts_as_citation_error(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Advisor productivity improved 18%. [^2]\n\n[^1]: A"
        state.report_footnote_evidence = {1: state.evidence_store[0].id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.citation_accuracy, 0.0)
        self.assertEqual(result.bad_case_categories["citation_error"], 1)

    def test_llm_mode_nulls_citation_accuracy_but_reports_resolution_rate(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.metadata["execution_mode"] = "llm"
        state.metadata["llm_usage"] = {
            "total_cost_cny": 0.000123,
            "price_source": "v4flash_console_calibrated_20260612",
        }
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Assets under management doubled in one quarter. [^1]\n\n[^1]: A"
        state.report_footnote_evidence = {1: state.evidence_store[0].id}

        result = Evaluator().evaluate(state)

        self.assertIsNone(result.citation_accuracy)
        self.assertIsNotNone(result.citation_accuracy_reason)
        self.assertEqual(result.citation_resolution_rate, 1.0)
        self.assertNotIn("citation_error", result.bad_case_categories)
        self.assertEqual(result.cost_cny, 0.000123)
        self.assertEqual(result.price_source, "v4flash_console_calibrated_20260612")

    def test_llm_mode_financial_numeric_mismatch_fails_task_without_inventing_score(
        self,
    ) -> None:
        state = self._state_with_financial_report(
            "贵州茅台2025年营业收入16883.81亿元，2024年1708.99亿元，"
            "同比下降1.21%；归母净利润823.20亿元；主营业务毛利率"
            "91.23%，同比下降0.78个百分点。"
        )
        state.metadata["execution_mode"] = "llm"

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 0.0)
        self.assertIsNone(result.citation_accuracy)
        self.assertEqual(result.citation_resolution_rate, 1.0)
        self.assertEqual(result.bad_case_categories["numeric_citation_mismatch"], 1)
        self.assertNotIn("citation_error", result.bad_case_categories)

    def test_llm_mode_reports_citation_repair_and_uncited_claim_rates(self) -> None:
        state = self._state_with_supported_report()
        state.metadata["execution_mode"] = "llm"
        state.metadata["llm_stats"] = {
            "reporter": {
                "citation_repair_retries": 1,
                "claim_provenance": [
                    {"has_citation": True},
                    {"has_citation": False},
                ],
            }
        }

        result = Evaluator().evaluate(state)

        self.assertEqual(result.citation_repair_retry_rate, 1.0)
        self.assertEqual(result.uncited_claim_rate, 0.5)

    def test_critic_issue_types_are_propagated_to_bad_case_categories(self) -> None:
        state = ResearchState(topic="wealth AI")
        state.evidence_store = [
            Evidence(
                research_id=state.research_id,
                sub_question_id="a",
                claim="Advisor productivity improved 18%.",
                claim_type="data",
                source_url="https://a.example",
                source_title="A",
                source_pub_date=date(2026, 1, 1),
                extract_text="Advisor productivity improved 18%.",
            )
        ]
        state.final_report = "- Advisor productivity improved 18%. [^1]\n\n[^1]: A"
        state.report_footnote_evidence = {1: state.evidence_store[0].id}
        state.critic_report = CriticReport(
            passed=False,
            overall_quality=0.4,
            issues=[
                Issue(
                    issue_type="numeric_conflict",
                    severity="high",
                    affected_claims=["Advisor productivity improved 18%."],
                    message="Conflicting productivity figures were found.",
                ),
                Issue(
                    issue_type="numeric_conflict",
                    severity="medium",
                    affected_claims=["Advisor productivity improved 18%."],
                    message="A second numeric conflict should increment the same category.",
                ),
                Issue(
                    issue_type="outdated_source",
                    severity="medium",
                    affected_claims=["Advisor productivity improved 18%."],
                    message="The supporting source is too old for this claim.",
                ),
            ],
        )

        result = Evaluator().evaluate(state)

        self.assertEqual(result.citation_accuracy, 1.0)
        self.assertEqual(result.bad_case_categories["numeric_conflict"], 2)
        self.assertEqual(result.bad_case_categories["outdated_source"], 1)
        self.assertNotIn("citation_error", result.bad_case_categories)

    def test_missing_historical_mapping_degrades_without_positional_inference(self) -> None:
        state = self._state_with_supported_report()
        state.report_footnote_evidence = {}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.citation_accuracy, 0.0)
        self.assertEqual(result.citation_resolution_rate, 0.0)
        self.assertEqual(result.bad_case_categories["citation_error"], 1)
        self.assertEqual(
            state.metadata["degradation_events"][-1]["reason"],
            "report_footnote_evidence_missing",
        )

    def test_critic_catch_rate_matches_issue_count_heuristic(self) -> None:
        cases = [
            ("without_critic_report", None, 1.0),
            ("with_empty_critic_report", 0, 1.0),
            ("with_one_issue", 1, 0.333),
            ("with_three_issues", 3, 1.0),
            ("with_four_issues", 4, 1.0),
        ]

        for name, issue_count, expected in cases:
            with self.subTest(name=name):
                state = self._state_with_supported_report()
                if issue_count is not None:
                    state.critic_report = CriticReport(
                        passed=issue_count == 0,
                        overall_quality=1.0 if issue_count == 0 else 0.4,
                        issues=[self._critic_issue(index) for index in range(issue_count)],
                    )

                result = Evaluator().evaluate(state)

                self.assertEqual(result.critic_catch_rate, expected)


if __name__ == "__main__":
    unittest.main()
