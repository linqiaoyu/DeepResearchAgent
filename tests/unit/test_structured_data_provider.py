from __future__ import annotations

import tempfile
import time
from decimal import Decimal
import unittest
from datetime import date
from pathlib import Path
from pydantic import ValidationError

from deepresearch_agent.agents import ResearcherAgent
from deepresearch_agent.schemas import (
    BoundingBox,
    Evidence,
    NumericFields,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.tools import (
    AKShareStructuredDataProvider,
    FixtureStructuredDataProvider,
    build_structured_data_provider,
)


class StructuredDataProviderTests(unittest.TestCase):
    def test_akshare_retry_is_not_queued_behind_a_timed_out_call(self) -> None:
        calls = 0

        def first_call_hangs_then_returns() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                time.sleep(0.1)
            return "available"

        provider = AKShareStructuredDataProvider(
            akshare_module=object(),
            timeout_seconds=0.01,
            max_retries=1,
            sleep_func=lambda _: None,
        )

        self.assertEqual(provider._call(first_call_hangs_then_returns, "probe"), "available")
        self.assertEqual(calls, 2)

    def test_financial_request_rejects_unparseable_period_before_execution(self) -> None:
        with self.assertRaisesRegex(ValidationError, "unparsable_periods=.*TTM"):
            StructuredDataRequest(
                capability="financial_indicators",
                symbol="300750",
                periods=["2024", "TTM"],
                metrics=["营业收入"],
            )

    def test_akshare_keeps_total_revenue_distinct_and_deduplicates_rows(self) -> None:
        class Frame:
            def __init__(self, rows: list[dict[str, object]]) -> None:
                self.rows = rows

            def to_dict(self, _orient: str) -> list[dict[str, object]]:
                return list(self.rows)

        class AKShareStub:
            def stock_financial_abstract(self, *, symbol: str) -> Frame:
                self.symbol = symbol
                revenue = {
                    "指标": "营业收入",
                    "20251231": 168_838_102_514.79,
                    "20241231": 170_899_152_276.34,
                }
                return Frame([
                    {
                        "指标": "营业总收入",
                        "20251231": 172_054_171_890.91,
                        "20241231": 174_144_069_958.25,
                    },
                    revenue,
                    dict(revenue),
                    {
                        "指标": "归母净利润",
                        "20251231": 82_320_067_101.68,
                        "20241231": 86_228_146_421.62,
                    },
                    {
                        "指标": "毛利率",
                        "20251231": 91.179551,
                        "20241231": 91.931216,
                    },
                ])

            def stock_info_a_code_name(self) -> Frame:
                return Frame([{"code": "600519", "name": "贵州茅台"}])

        provider = AKShareStructuredDataProvider(
            akshare_module=AKShareStub(),
            max_retries=0,
        )

        records = provider.financial_indicators(
            "600519",
            periods=["2025", "20241231"],
            metrics=["营业收入", "归母净利润"],
        )
        main_business_margin = provider.financial_indicators(
            "600519",
            periods=["2025"],
            metrics=["主营业务毛利率"],
        )

        self.assertEqual(len(records), 4)
        self.assertEqual(
            {
                (record.metric_name, record.period): record.value
                for record in records
            },
            {
                ("营业收入", "20251231"): Decimal("168838102514.79"),
                ("营业收入", "20241231"): Decimal("170899152276.34"),
                ("归母净利润", "20251231"): Decimal("82320067101.68"),
                ("归母净利润", "20241231"): Decimal("86228146421.62"),
            },
        )
        self.assertNotIn(
            174_144_069_958.25,
            {record.value for record in records},
        )
        self.assertEqual(main_business_margin, [])

    def test_akshare_known_symbol_skips_resolution_and_non_finite_values(self) -> None:
        class Frame:
            def to_dict(self, _orient: str) -> list[dict[str, object]]:
                return [{"指标": "营业收入", "20241231": 10.0, "20231231": float("nan")}]

        class AKShareStub:
            def stock_financial_abstract(self, *, symbol: str) -> Frame:
                self.symbol = symbol
                return Frame()

            def stock_info_a_code_name(self) -> Frame:
                raise AssertionError("known symbol must not trigger resolution")

        provider = AKShareStructuredDataProvider(akshare_module=AKShareStub())
        records = provider.financial_indicators("300750", metrics=["营业收入"])

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].entity, "300750")
        self.assertEqual(records[0].period, "20241231")

    def test_fixture_symbol_resolve_and_financial_indicator_normalization(self) -> None:
        provider = FixtureStructuredDataProvider()

        symbol = provider.symbol_resolve("宁德时代")
        records = provider.financial_indicators(
            "300750",
            periods=["20241231"],
            metrics=["营收", "归母净利润"],
        )

        self.assertIsNotNone(symbol)
        self.assertEqual(symbol.symbol, "300750")
        self.assertEqual({record.metric_name for record in records}, {"营业收入", "归母净利润"})
        for record in records:
            self.assertEqual(record.entity, "宁德时代")
            self.assertEqual(record.dimension, "累计")
            self.assertEqual(record.data_source, "AKShare: stock_financial_abstract")
            self.assertGreater(record.value, 0)

    def test_fixture_price_history_returns_date_filtered_records(self) -> None:
        provider = FixtureStructuredDataProvider()

        records = provider.price_history("300750", date(2024, 1, 2), date(2024, 1, 2))

        self.assertEqual({record.period for record in records}, {"2024-01-02"})
        self.assertIn("收盘价", {record.metric_name for record in records})

    def test_factory_defaults_to_fixture_provider(self) -> None:
        provider = build_structured_data_provider({})

        self.assertIsInstance(provider, FixtureStructuredDataProvider)

    def test_sqlite_store_persists_structured_evidence_metadata(self) -> None:
        provider = FixtureStructuredDataProvider()
        record = provider.financial_indicators("300750", periods=["20241231"], metrics=["归母净利润"])[0]
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(Path(tmp) / "research.db")
            evidence = Evidence(
                research_id="run-1",
                sub_question_id="sq-1",
                claim="宁德时代 2024 年累计归母净利润为 507.45 亿元。",
                claim_type="data",
                source_kind="structured",
                source_tier="primary",
                content_truncated=True,
                source_url="akshare://financial_indicators/300750/20241231/归母净利润",
                source_title="AKShare financial_indicators 300750 20241231 归母净利润",
                source_pub_date=record.as_of,
                extract_text="宁德时代|归母净利润|20241231|累计|50744680000.0|元",
                bbox=BoundingBox(page=1, x0=10, top=20, x1=30, bottom=40),
                structured_record=record,
                numeric_fields=NumericFields(
                    entity=record.entity,
                    metric_name=record.metric_name,
                    period=record.period,
                    dimension=record.dimension,
                    value=record.value,
                    unit=record.unit,
                ),
            )

            store.add_evidence_many([evidence])
            loaded = store.list_evidence("run-1")[0]

        self.assertEqual(loaded.source_kind, "structured")
        self.assertEqual(loaded.source_tier, "primary")
        self.assertTrue(loaded.content_truncated)
        self.assertIsNotNone(loaded.structured_record)
        self.assertEqual(loaded.structured_record.metric_name, "归母净利润")
        self.assertIsNotNone(loaded.numeric_fields)
        self.assertEqual(loaded.numeric_fields.metric_name, "归母净利润")
        self.assertEqual(loaded.bbox, BoundingBox(page=1, x0=10, top=20, x1=30, bottom=40))

    def test_researcher_executes_structured_requests_as_evidence(self) -> None:
        researcher = ResearcherAgent(structured_data_provider=FixtureStructuredDataProvider())
        sub_question = SubQuestion(
            id="finance",
            question="宁德时代 2024 年业绩如何？",
            search_queries=[],
            structured_data_requests=[
                StructuredDataRequest(
                    capability="financial_indicators",
                    symbol="300750",
                    periods=["20241231"],
                    metrics=["归母净利润"],
                )
            ],
        )

        evidence, stats, _resolutions = researcher.structured_evidence("run-1", sub_question)

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].source_kind, "structured")
        self.assertEqual(evidence[0].claim_type, "data")
        self.assertIsNotNone(evidence[0].structured_record)
        self.assertEqual(evidence[0].structured_record.metric_name, "归母净利润")
        self.assertIsNotNone(evidence[0].numeric_fields)
        self.assertEqual(evidence[0].numeric_fields.period, "20241231")
        self.assertEqual(stats["records"], 1)

    def test_unresolved_symbol_is_recorded_as_a_structured_failure(self) -> None:
        researcher = ResearcherAgent(structured_data_provider=FixtureStructuredDataProvider())
        sub_question = SubQuestion(
            id="finance",
            question="未知公司业绩",
            search_queries=[],
            structured_data_requests=[
                StructuredDataRequest(
                    capability="financial_indicators",
                    company_name="不存在的公司",
                    periods=["2024"],
                    metrics=["营业收入"],
                )
            ],
        )

        evidence, stats, _resolutions = researcher.structured_evidence("run-1", sub_question)

        self.assertEqual(evidence, [])
        self.assertEqual(stats["symbol_resolution_failures"], 1)
        self.assertEqual(stats["failures"][0]["error_type"], "SymbolResolutionError")

    def test_structured_numeric_mirror_preserves_decimal_exactly(self) -> None:
        researcher = ResearcherAgent(structured_data_provider=FixtureStructuredDataProvider())
        record = next(
            item
            for item in researcher.structured_data_provider.financial_indicators(
                "300750", periods=["20241231"], metrics=["归母净利润"]
            )
        )
        evidence = researcher._evidence_from_record("run-1", "finance", record)
        assert evidence.numeric_fields is not None
        self.assertIsInstance(evidence.numeric_fields.value, Decimal)
        self.assertEqual(evidence.numeric_fields.value, record.value)

    def test_symbol_resolve_records_metadata_not_evidence(self) -> None:
        researcher = ResearcherAgent(structured_data_provider=FixtureStructuredDataProvider())
        sub_question = SubQuestion(
            id="resolve",
            question="宁德时代代码是什么？",
            search_queries=[],
            structured_data_requests=[
                StructuredDataRequest(capability="symbol_resolve", company_name="宁德时代")
            ],
        )

        evidence, stats, resolutions = researcher.structured_evidence("run-1", sub_question)

        self.assertEqual(evidence, [])
        self.assertEqual(stats["records"], 0)
        self.assertEqual(resolutions[0]["symbol"], "300750")


if __name__ == "__main__":
    unittest.main()
