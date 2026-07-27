from __future__ import annotations

import unittest
from decimal import Decimal
from datetime import date
from types import SimpleNamespace

from deepresearch_agent.agents import ExtractorAgent
from deepresearch_agent.agents.evaluator import Evaluator
from deepresearch_agent.domains.finance.table_extraction import (
    authoritative_financial_backfills,
)
from deepresearch_agent.metric_coverage import (
    evaluate_metric_coverage,
)
from deepresearch_agent.schemas import (
    Evidence,
    ExtractedClaim,
    ExtractedClaims,
    NumericFields,
    ResearchPlan,
    ResearchState,
    Source,
    StructuredDataRequest,
    SubQuestion,
)


class _ExtractorLLM:
    def __init__(self, claims: list[ExtractedClaim]) -> None:
        self.claims = claims

    def complete(self, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            parsed=ExtractedClaims(claims=self.claims),
            repair_attempts=0,
        )


class _FailingExtractorLLM:
    def complete(self, **_kwargs: object) -> SimpleNamespace:
        raise ValueError("synthetic extractor failure")


class FinancialTableExtractorTests(unittest.TestCase):
    def test_statement_table_index_backfills_without_text_row(self) -> None:
        sub_question = self._sub_question(metrics=["营业收入"])
        source = Source(
            title="贵州茅台酒股份有限公司2025年年度报告",
            url="fixture://primary/table-only",
            source_type="disclosure_pdf",
            source_tier="primary",
            published_at=date(2026, 4, 16),
            content="[[PDF_PAGE=6]]\n2025年年度报告\n单位：元\n主要会计数据",
            table_index=[
                [
                    ["主要会计数据", "2025年", "2024年", "同比(%)", "2023年"],
                    [
                        "营业收入",
                        "168,838,102,514.79",
                        "170,899,152,276.34",
                        "-1.21",
                        "147,693,604,994.14",
                    ],
                ]
            ],
        )

        evidence = authoritative_financial_backfills(
            "research",
            sub_question,
            [source],
        )

        self.assertEqual(len(evidence), 2)
        self.assertEqual(
            {item.numeric_fields.period for item in evidence if item.numeric_fields},
            {"2024年", "2025年"},
        )

    def test_legacy_unparseable_period_remains_an_explicit_coverage_gap(self) -> None:
        # model_construct represents a persisted/replayed state created before
        # StructuredDataRequest gained its fail-closed validator.
        request = StructuredDataRequest.model_construct(
            capability="financial_indicators",
            company_name="贵州茅台",
            symbol="600519",
            periods=["2024", "TTM"],
            metrics=["营业收入"],
            start_date=None,
            end_date=None,
        )
        state = ResearchState(topic="贵州茅台营业收入")
        state.plan = ResearchPlan.model_construct(
            topic="贵州茅台营业收入",
            depth_level=2,
            sub_questions=[
                SubQuestion.model_construct(
                    id="finance",
                    question="营业收入",
                    search_queries=[],
                    expected_source_types=[],
                    structured_data_requests=[request],
                    priority=3,
                )
            ],
            estimated_sources=6,
            success_criteria=[],
        )
        state.completed_tasks = ["finance"]

        coverage = evaluate_metric_coverage(state)

        self.assertEqual(coverage[0].status, "unparsable_period")
        self.assertEqual(coverage[0].missing_periods, ["TTM", "2024"])

    def _sub_question(
        self,
        metrics: list[str] | None = None,
    ) -> SubQuestion:
        return SubQuestion(
            id="finance",
            question="贵州茅台 2025 年财务指标及同比",
            search_queries=["600519 年度报告"],
            structured_data_requests=[
                StructuredDataRequest(
                    capability="financial_indicators",
                    company_name="贵州茅台",
                    symbol="600519",
                    periods=["20251231", "20241231"],
                    metrics=metrics
                    or [
                        "营业收入",
                        "归母净利润",
                        "主营业务毛利率",
                    ],
                )
            ],
        )

    def _annual_report(
        self,
        industry_rows: str | None = None,
    ) -> Source:
        rows = industry_rows or (
            "酒类 168,774,585,187.65 14,805,900,139.59 "
            "91.23 -1.08 8.63 减少 0.78 个百\n分点\n"
        )
        content = (
            "[[PDF_PAGE=6]]\n"
            "贵州茅台酒股份有限公司2025 年年度报告\n"
            "七、近三年主要会计数据和财务指标\n"
            "(一) 主要会计数据\n"
            "单位：元 币种：人民币\n"
            "主要会计数据 2025年 2024年 本期比上年同期增减(%) 2023年\n"
            "营业收入 168,838,102,514.79 "
            "170,899,152,276.34 -1.21 147,693,604,994.14\n"
            "利润总额 114,755,261,605.08 "
            "119,638,578,194.46 -4.08 103,662,553,689.81\n"
            "归属于上市公司股东的净利润 82,320,067,101.68 "
            "86,228,146,421.62 -4.53 74,734,071,550.75\n"
            "[[PDF_PAGE=10]]\n"
            "贵州茅台酒股份有限公司2025 年年度报告\n"
            "2、收入和成本分析\n"
            "(1). 主营业务分行业、分产品、分地区、分销售模式情况\n"
            "单位：元 币种：人民币\n"
            "主营业务分行业情况\n"
            "分行业 营业收入 营业成本 毛利率（%） 营业收入比上\n"
            "年增减（%） 营业成本比上\n"
            "年增减（%） 毛利率比上年\n"
            "增减（%）\n"
            f"{rows}"
            "主营业务分产品情况\n"
            "分产品 营业收入 营业成本 毛利率（%）\n"
            "茅台酒 146,499,906,480.49 "
            "9,484,757,825.54 93.53 0.39 9.50 "
            "减少 0.53 个百\n分点\n"
        )
        return Source(
            title="贵州茅台2025年年度报告",
            url="https://static.cninfo.test/annual.PDF",
            source_type="disclosure_pdf",
            published_at=date(2026, 4, 16),
            content=content,
            source_tier="primary",
            content_truncated=True,
        )

    def test_invalid_llm_margin_is_rejected_then_backfilled_verbatim(
        self,
    ) -> None:
        source = self._annual_report()
        invalid_margin = ExtractedClaim(
            claim="主营业务毛利率为91.23%，同比下降0.78个百分点。",
            claim_type="data",
            source_url=source.url,
            extract_text=(
                "毛利率（%） 91.23 减少 0.78 个百分点"
            ),
            confidence=0.95,
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="主营业务毛利率",
                period="2025年",
                dimension="酒类",
                value=91.23,
                unit="%",
            ),
        )
        extractor = ExtractorAgent(
            llm_client=_ExtractorLLM(  # type: ignore[arg-type]
                [invalid_margin]
            )
        )
        sub_question = self._sub_question()

        evidence = extractor.extract(
            "financial-backfill",
            sub_question,
            [source],
        )

        margin = next(
            item
            for item in evidence
            if item.numeric_fields
            and item.numeric_fields.metric_name
            == "主营业务毛利率"
        )
        self.assertEqual(
            extractor.last_stats["invalid_extract_text"],
            1,
        )
        self.assertEqual(
            extractor.last_stats[
                "authoritative_financial_backfills"
            ],
            5,
        )
        self.assertEqual(margin.source_page, 10)
        self.assertEqual(margin.numeric_fields.value, Decimal("91.23"))
        self.assertEqual(
            margin.numeric_fields.dimension,
            "主营业务分行业：酒类",
        )
        self.assertIn("下降0.78个百分点", margin.claim)
        self.assertIn(
            "酒类 168,774,585,187.65",
            margin.extract_text,
        )
        self.assertNotIn(
            "主营业务分产品情况",
            margin.extract_text,
        )
        self.assertEqual(
            source.content[
                margin.extract_offset_start:
                margin.extract_offset_start
                + len(margin.extract_text)
            ],
            margin.extract_text,
        )
        state = ResearchState(
            research_id="financial-backfill",
            topic=sub_question.question,
            plan=ResearchPlan(
                topic=sub_question.question,
                sub_questions=[sub_question],
            ),
            evidence_store=evidence,
        )
        state.completed_tasks = ["finance"]
        state.final_report = (
            "- 2025年主营业务毛利率为91.23%，"
            "较2024年下降0.78个百分点。 [^1]\n\n"
            "[^1]: 贵州茅台2025年年度报告 p10"
        )
        state.report_footnote_evidence = {1: margin.id}

        result = Evaluator().evaluate(state)
        coverage = {
            item.metric: item.status
            for item in evaluate_metric_coverage(state)
        }

        self.assertEqual(result.task_success_rate, 1.0)
        self.assertEqual(
            coverage,
            {
                "主营业务毛利率": "partially_cited",
                "归母净利润": "cited",
                "营业收入": "cited",
            },
        )
        self.assertNotIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

    def test_deterministic_extractor_preserves_and_backfills_evidence(
        self,
    ) -> None:
        evidence = ExtractorAgent().extract(
            "deterministic-backfill",
            self._sub_question(),
            [self._annual_report()],
        )

        typed = [
            item
            for item in evidence
            if item.numeric_fields is not None
        ]
        self.assertEqual(len(typed), 5)
        self.assertEqual(
            {
                (
                    item.numeric_fields.metric_name,
                    item.numeric_fields.period,
                )
                for item in typed
                if item.numeric_fields
            },
            {
                ("营业收入", "2025年"),
                ("营业收入", "2024年"),
                ("归母净利润", "2025年"),
                ("归母净利润", "2024年"),
                ("主营业务毛利率", "2025年"),
            },
        )

    def test_llm_failure_falls_back_then_backfills_evidence(
        self,
    ) -> None:
        extractor = ExtractorAgent(
            llm_client=_FailingExtractorLLM(),  # type: ignore[arg-type]
        )

        evidence = extractor.extract(
            "failed-llm-backfill",
            self._sub_question(),
            [self._annual_report()],
        )

        self.assertTrue(extractor.last_stats["fallback"])
        self.assertEqual(
            extractor.last_stats[
                "authoritative_financial_backfills"
            ],
            5,
        )
        self.assertEqual(
            len(
                [
                    item
                    for item in evidence
                    if item.numeric_fields is not None
                ]
            ),
            5,
        )

    def test_statement_rows_backfill_both_requested_periods(
        self,
    ) -> None:
        source = self._annual_report()
        sub_question = self._sub_question(
            ["营业收入", "归母净利润"]
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "statement-backfill",
            sub_question,
            [source],
        )

        observed = {
            (
                item.numeric_fields.metric_name,
                item.numeric_fields.period,
                item.numeric_fields.value,
                item.source_page,
            )
            for item in evidence
            if item.numeric_fields
        }
        self.assertEqual(
            observed,
            {
                (
                    "营业收入",
                    "2025年",
                    Decimal("168838102514.79"),
                    6,
                ),
                (
                    "营业收入",
                    "2024年",
                    Decimal("170899152276.34"),
                    6,
                ),
                (
                    "归母净利润",
                    "2025年",
                    Decimal("82320067101.68"),
                    6,
                ),
                (
                    "归母净利润",
                    "2024年",
                    Decimal("86228146421.62"),
                    6,
                ),
            },
        )
        self.assertTrue(
            all(
                item.extract_text
                in source.content
                for item in evidence
            )
        )

    def test_financial_evidence_ids_survive_redacted_prefix_length_change(
        self,
    ) -> None:
        source = self._annual_report().model_copy(
            update={
                "content": (
                    "投资者邮箱：ir@moutai.example\n"
                    + self._annual_report().content
                )
            }
        )
        redacted = source.model_copy(
            update={
                "content": source.content.replace(
                    "ir@moutai.example",
                    "[REDACTED_EMAIL]",
                )
            }
        )
        sub_question = self._sub_question()

        original = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "redaction-stable",
            sub_question,
            [source],
        )
        replayed = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "redaction-stable",
            sub_question,
            [redacted],
        )

        self.assertNotEqual(
            [item.extract_offset_start for item in original],
            [item.extract_offset_start for item in replayed],
        )
        self.assertEqual(
            [item.id for item in original],
            [item.id for item in replayed],
        )

    def test_multiple_industry_rows_without_total_fail_closed(
        self,
    ) -> None:
        source = self._annual_report(
            industry_rows=(
                "业务甲 1,000.00 100.00 90.00 1.00 2.00 "
                "减少 0.20 个百分点\n"
                "业务乙 2,000.00 400.00 80.00 3.00 4.00 "
                "增加 0.10 个百分点\n"
            )
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "ambiguous-margin",
            self._sub_question(["主营业务毛利率"]),
            [source],
        )

        self.assertEqual(evidence, [])

    def test_multiple_industry_rows_choose_explicit_total(
        self,
    ) -> None:
        source = self._annual_report(
            industry_rows=(
                "业务甲 1,000.00 100.00 90.00 1.00 2.00 "
                "减少 0.20 个百分点\n"
                "业务乙 2,000.00 400.00 80.00 3.00 4.00 "
                "增加 0.10 个百分点\n"
                "合计 3,000.00 500.00 83.33 2.00 3.00 "
                "减少 0.15 个百分点\n"
            )
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "total-margin",
            self._sub_question(["主营业务毛利率"]),
            [source],
        )

        self.assertEqual(len(evidence), 1)
        fields = evidence[0].numeric_fields
        assert fields is not None
        self.assertEqual(fields.value, Decimal("83.33"))
        self.assertEqual(
            fields.dimension,
            "主营业务分行业：合计",
        )

    def test_product_row_alone_cannot_backfill_main_business(
        self,
    ) -> None:
        source = self._annual_report()
        source = source.model_copy(
            update={
                "content": source.content.replace(
                    "主营业务分行业情况",
                    "行业信息未披露",
                    1,
                )
            }
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "product-only",
            self._sub_question(["主营业务毛利率"]),
            [source],
        )

        self.assertEqual(evidence, [])

    def test_secondary_or_summary_pdf_is_not_backfilled(
        self,
    ) -> None:
        source = self._annual_report()
        sub_question = self._sub_question(["营业收入"])
        extractor = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        )

        secondary = extractor.extract(
            "secondary",
            sub_question,
            [
                source.model_copy(
                    update={"source_tier": "secondary"}
                )
            ],
        )
        summary = extractor.extract(
            "summary",
            sub_question,
            [
                source.model_copy(
                    update={
                        "title": "贵州茅台2025年年度报告摘要"
                    }
                )
            ],
        )

        self.assertEqual(secondary, [])
        self.assertEqual(summary, [])

    def test_wrong_issuer_or_report_year_is_not_backfilled(
        self,
    ) -> None:
        source = self._annual_report()
        sub_question = self._sub_question(["主营业务毛利率"])
        extractor = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        )

        wrong_issuer = extractor.extract(
            "wrong-issuer",
            sub_question,
            [
                source.model_copy(
                    update={
                        "title": "其他公司2025年年度报告",
                        "content": source.content.replace(
                            "贵州茅台",
                            "其他公司",
                        ),
                    }
                )
            ],
        )
        wrong_year = extractor.extract(
            "wrong-year",
            sub_question,
            [
                source.model_copy(
                    update={
                        "title": "贵州茅台2024年年度报告",
                        "content": source.content.replace(
                            "2025 年年度报告",
                            "2024 年年度报告",
                        ),
                    }
                )
            ],
        )

        self.assertEqual(wrong_issuer, [])
        self.assertEqual(wrong_year, [])

    def test_disclosed_statement_yoy_must_reconcile(
        self,
    ) -> None:
        source = self._annual_report().model_copy(
            update={
                "content": self._annual_report().content.replace(
                    "170,899,152,276.34 -1.21",
                    "170,899,152,276.34 9.99",
                )
            }
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "bad-yoy",
            self._sub_question(["营业收入"]),
            [source],
        )

        self.assertEqual(evidence, [])

    def test_disclosed_margin_must_reconcile_with_revenue_and_cost(
        self,
    ) -> None:
        source = self._annual_report().model_copy(
            update={
                "content": self._annual_report().content.replace(
                    "91.23 -1.08 8.63",
                    "99.99 -1.08 8.63",
                    1,
                )
            }
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "bad-margin",
            self._sub_question(["主营业务毛利率"]),
            [source],
        )

        self.assertEqual(evidence, [])

    def test_margin_change_requires_percentage_point_unit(
        self,
    ) -> None:
        source = self._annual_report(
            industry_rows=(
                "制造业 1,000.00 100.00 90.00 1.00 2.00 "
                "减少 0.20 %\n"
            )
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "wrong-margin-unit",
            self._sub_question(["主营业务毛利率"]),
            [source],
        )

        self.assertEqual(evidence, [])

    def test_margin_change_rejects_label_sign_conflict(
        self,
    ) -> None:
        source = self._annual_report(
            industry_rows=(
                "制造业 1,000.00 100.00 90.00 1.00 2.00 "
                "减少 -0.20 个百分点\n"
            )
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "conflicting-margin-direction",
            self._sub_question(["主营业务毛利率"]),
            [source],
        )

        self.assertEqual(evidence, [])

    def test_generic_unique_industry_label_supports_margin_yoy(
        self,
    ) -> None:
        source = self._annual_report(
            industry_rows=(
                "制造业 1,000.00 100.00 90.00 1.00 2.00 "
                "减少 0.20 个百分点\n"
            )
        )
        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "generic-industry",
            self._sub_question(["主营业务毛利率"]),
            [source],
        )
        self.assertEqual(len(evidence), 1)
        margin = evidence[0]
        fields = margin.numeric_fields
        assert fields is not None
        self.assertEqual(
            fields.dimension,
            "主营业务分行业：制造业",
        )
        state = ResearchState(
            research_id="generic-industry",
            topic="另一家公司 2025 年主营业务毛利率及同比",
            evidence_store=[margin],
        )
        state.final_report = (
            "- 2025年主营业务毛利率为90.00%，"
            "较2024年下降0.20个百分点。 [^1]\n\n"
            "[^1]: 2025年年度报告 p10"
        )
        state.report_footnote_evidence = {1: margin.id}

        result = Evaluator().evaluate(state)

        self.assertEqual(result.task_success_rate, 1.0)
        self.assertNotIn(
            "numeric_citation_mismatch",
            result.bad_case_categories,
        )

    def test_existing_typed_period_is_not_duplicated(
        self,
    ) -> None:
        source = self._annual_report()
        sub_question = self._sub_question(["营业收入"])
        existing = Evidence(
            research_id="dedupe",
            sub_question_id="finance",
            claim="2025年营业收入为168,838,102,514.79元。",
            claim_type="data",
            source_url=source.url,
            source_title=source.title,
            source_pub_date=source.published_at,
            source_page=6,
            extract_text=(
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
        extractor = ExtractorAgent(
            llm_client=_ExtractorLLM(  # type: ignore[arg-type]
                [
                    ExtractedClaim(
                        claim=existing.claim,
                        claim_type="data",
                        source_url=existing.source_url,
                        extract_text=existing.extract_text,
                        confidence=0.99,
                        numeric_fields=existing.numeric_fields,
                    )
                ]
            )
        )

        evidence = extractor.extract(
            "dedupe",
            sub_question,
            [source],
        )

        periods = [
            item.numeric_fields.period
            for item in evidence
            if item.numeric_fields
            and item.numeric_fields.metric_name == "营业收入"
        ]
        self.assertEqual(periods.count("2025年"), 1)
        self.assertEqual(periods.count("2024年"), 1)

    def test_nonconsecutive_requested_period_uses_named_header_column(
        self,
    ) -> None:
        source = self._annual_report()
        sub_question = self._sub_question(
            ["营业收入", "归母净利润"]
        )
        request = sub_question.structured_data_requests[0]
        sub_question = sub_question.model_copy(
            update={
                "structured_data_requests": [
                    request.model_copy(
                        update={
                            "periods": [
                                "20251231",
                                "20231231",
                            ]
                        }
                    )
                ]
            }
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "nonconsecutive",
            sub_question,
            [source],
        )

        observed = {
            (
                item.numeric_fields.metric_name,
                item.numeric_fields.period,
            ): item.numeric_fields.value
            for item in evidence
            if item.numeric_fields
        }
        self.assertEqual(
            observed[
                ("营业收入", "2023年")
            ],
            Decimal("147693604994.14"),
        )
        self.assertEqual(
            observed[
                ("归母净利润", "2023年")
            ],
            74_734_071_550.75,
        )
        self.assertNotIn(
            170_899_152_276.34,
            {
                value
                for (metric, period), value in observed.items()
                if period == "2023年"
                and metric == "营业收入"
            },
        )

    def test_reversed_current_year_header_fails_closed(
        self,
    ) -> None:
        source = self._annual_report().model_copy(
            update={
                "content": self._annual_report().content.replace(
                    "主要会计数据 2025年 2024年",
                    "主要会计数据 2024年 2025年",
                )
            }
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "reversed-header",
            self._sub_question(
                ["营业收入", "归母净利润"]
            ),
            [source],
        )

        self.assertEqual(evidence, [])

    def test_wrong_llm_period_value_is_replaced_by_authoritative_row(
        self,
    ) -> None:
        source = self._annual_report()
        extract_text = (
            "营业收入 168,838,102,514.79 "
            "170,899,152,276.34 -1.21 "
            "147,693,604,994.14"
        )
        wrong = ExtractedClaim(
            claim="2025年营业收入为170,899,152,276.34元。",
            claim_type="data",
            source_url=source.url,
            extract_text=extract_text,
            confidence=0.95,
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="营业收入",
                period="2025年",
                dimension="年度主要会计数据",
                value=170_899_152_276.34,
                unit="元",
            ),
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM(  # type: ignore[arg-type]
                [wrong]
            )
        ).extract(
            "wrong-period-value",
            self._sub_question(["营业收入"]),
            [source],
        )

        values = {
            item.numeric_fields.period:
            item.numeric_fields.value
            for item in evidence
            if item.numeric_fields
            and item.numeric_fields.metric_name == "营业收入"
        }
        self.assertEqual(
            values,
            {
                "2024年": Decimal("170899152276.34"),
                "2025年": Decimal("168838102514.79"),
            },
        )

    def test_product_margin_with_forged_dimension_is_replaced(
        self,
    ) -> None:
        source = self._annual_report()
        product_extract = (
            "茅台酒 146,499,906,480.49 "
            "9,484,757,825.54 93.53 0.39 9.50 "
            "减少 0.53 个百\n分点"
        )
        wrong = ExtractedClaim(
            claim="主营业务毛利率为93.53%。",
            claim_type="data",
            source_url=source.url,
            extract_text=product_extract,
            confidence=0.95,
            numeric_fields=NumericFields(
                entity="贵州茅台",
                metric_name="主营业务毛利率",
                period="2025年",
                dimension="主营业务分行业：酒类",
                value=93.53,
                unit="%",
            ),
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM(  # type: ignore[arg-type]
                [wrong]
            )
        ).extract(
            "forged-margin",
            self._sub_question(["主营业务毛利率"]),
            [source],
        )

        margins = [
            item
            for item in evidence
            if item.numeric_fields
            and item.numeric_fields.metric_name
            == "主营业务毛利率"
        ]
        self.assertEqual(len(margins), 1)
        self.assertEqual(
            margins[0].numeric_fields.value,
            Decimal("91.23"),
        )
        self.assertNotIn(
            "茅台酒 146,499",
            margins[0].extract_text,
        )

    def test_different_issuer_year_and_unit_uses_same_parser(
        self,
    ) -> None:
        source = self._annual_report()
        content = (
            source.content
            .replace("贵州茅台", "示例制造")
            .replace(
                "2025 年年度报告",
                "2027 年年度报告",
            )
            .replace(
                "主要会计数据 2025年 2024年",
                "主要会计数据 2027年 2026年",
            )
            .replace("2023年\n营业收入", "2025年\n营业收入")
            .replace("单位：元", "单位：万元")
        )
        source = source.model_copy(
            update={
                "title": "示例制造2027年年度报告",
                "content": content,
            }
        )
        sub_question = self._sub_question(["营业收入"])
        request = sub_question.structured_data_requests[0]
        sub_question = sub_question.model_copy(
            update={
                "question": "示例制造 2027 年营业收入",
                "structured_data_requests": [
                    request.model_copy(
                        update={
                            "company_name": "示例制造",
                            "symbol": "000001",
                            "periods": [
                                "20271231",
                                "20261231",
                            ],
                        }
                    )
                ],
            }
        )

        evidence = ExtractorAgent(
            llm_client=_ExtractorLLM([]),  # type: ignore[arg-type]
        ).extract(
            "other-issuer",
            sub_question,
            [source],
        )

        self.assertEqual(len(evidence), 2)
        self.assertEqual(
            {
                (
                    item.numeric_fields.entity,
                    item.numeric_fields.period,
                    item.numeric_fields.unit,
                )
                for item in evidence
                if item.numeric_fields
            },
            {
                ("示例制造", "2027年", "万元"),
                ("示例制造", "2026年", "万元"),
            },
        )


if __name__ == "__main__":
    unittest.main()
