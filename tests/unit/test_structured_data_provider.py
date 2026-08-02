from __future__ import annotations

import tempfile
import time
import multiprocessing
from decimal import Decimal
import unittest
from datetime import date
from pathlib import Path
from pydantic import ValidationError
from unittest import mock

import httpx

from deepresearch_agent.agents import ResearcherAgent
from deepresearch_agent.schemas import (
    BoundingBox,
    Evidence,
    NumericFields,
    StructuredDataRecord,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import (
    AKShareStructuredDataProvider,
    FixtureStructuredDataProvider,
    RunToolContext,
    SecCompanyFactsProvider,
    ToolExecutionError,
    build_structured_data_provider,
)
from deepresearch_agent.tools.structured_data_factory import OptionalProviderDependencyError
from deepresearch_agent.workflow import DeepResearchEngine


class StructuredDataProviderTests(unittest.TestCase):
    def test_sec_companyfacts_resolves_domain_alias_and_keeps_20f_fact_provenance(self) -> None:
        requested_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_urls.append(str(request.url))
            if request.url.path == "/files/company_tickers.json":
                return httpx.Response(200, json={
                    "0": {
                        "cik_str": 1577552,
                        "ticker": "BABA",
                        "title": "Alibaba Group Holding Ltd",
                    }
                })
            if request.url.path.endswith("CIK0001577552.json"):
                return httpx.Response(200, json={
                    "facts": {
                        "us-gaap": {
                            "Revenues": {"units": {"CNY": [
                                {
                                    "form": "20-F", "fp": "FY", "fy": 2024,
                                    "start": "2023-04-01", "end": "2024-03-31",
                                    "filed": "2024-05-23", "accn": "0000950170-24-063767",
                                    "val": 941168000000,
                                },
                                {
                                    "form": "6-K", "fp": "FY", "fy": 2024,
                                    "end": "2024-03-31", "filed": "2024-06-01",
                                    "accn": "0000950170-24-000001", "val": 1,
                                },
                            ]}},
                            "NetIncomeLoss": {"units": {"CNY": [{
                                "form": "20-F", "fp": "FY", "fy": 2024,
                                "start": "2023-04-01", "end": "2024-03-31",
                                "filed": "2024-05-23", "accn": "0000950170-24-063767",
                                "val": 80009000000,
                            }]}},
                        }
                    }
                })
            return httpx.Response(404)

        class Domain:
            def expand_retrieval_query(self, _query: str) -> str:
                return "阿里巴巴 Alibaba Group Holding Limited"

            @staticmethod
            def structured_xbrl_concepts() -> dict[str, tuple[str, ...]]:
                return {
                    "营业收入": ("Revenues",),
                    "归母净利润": ("NetIncomeLoss",),
                }

        provider = SecCompanyFactsProvider(
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_retries=0,
            domain_pack=Domain(),
        )
        symbol = provider.symbol_resolve("阿里巴巴")
        records = provider.financial_indicators(
            symbol.symbol if symbol else "", periods=["20240331"],
            metrics=["营业收入", "归母净利润", "扣非净利润"],
        )

        self.assertIsNotNone(symbol)
        self.assertEqual(symbol.symbol, "CIK0001577552")
        self.assertEqual(
            {(item.metric_name, item.value, item.period) for item in records},
            {
                ("营业收入", Decimal("941168000000"), "2024-03-31"),
                ("归母净利润", Decimal("80009000000"), "2024-03-31"),
            },
        )
        self.assertTrue(all(item.unit == "CNY" for item in records))
        self.assertTrue(all(item.source_pub_date == date(2024, 5, 23) for item in records))
        self.assertTrue(all(item.source_url and "000095017024063767" in item.source_url for item in records))
        self.assertEqual(len(requested_urls), 2)

    def test_researcher_never_uses_structured_retrieval_time_as_publication_date(self) -> None:
        record = StructuredDataRecord(
            entity="Example", symbol="EX", metric_name="revenue", period="2019",
            dimension="annual", value=Decimal("1"), unit="USD",
            data_source="provider", as_of=date(2026, 8, 2), source_pub_date=None,
        )

        evidence = ResearcherAgent()._evidence_from_record("run", "question", record)

        self.assertIsNone(evidence.source_pub_date)

    def test_sec_companyfacts_retries_bounded_http_failure(self) -> None:
        attempts = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(503, request=request)
            return httpx.Response(200, json={"0": {
                "cik_str": 1577552, "ticker": "BABA", "title": "Alibaba Group Holding Ltd",
            }})

        provider = SecCompanyFactsProvider(
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_retries=1,
            sleep_func=lambda _delay: None,
        )

        self.assertEqual(provider.symbol_resolve("BABA").symbol, "CIK0001577552")
        self.assertEqual(attempts, 2)

    def test_sec_companyfacts_counts_each_egress_against_the_bound_run_budget(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"0": {
                "cik_str": 1577552, "ticker": "BABA", "title": "Alibaba Group Holding Ltd",
            }}, request=request)

        context = RunToolContext.for_run(max_external_fetch_requests=1)
        provider = SecCompanyFactsProvider(
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_retries=0,
            context=context,
        )

        self.assertIsNotNone(provider.symbol_resolve("BABA"))
        with self.assertRaises(ToolExecutionError):
            provider.financial_indicators("CIK0001577552", periods=["20240331"])
        self.assertEqual(context.external_request_budget.snapshot()["fetch_requests"], 1)

    def test_researcher_records_sec_price_request_as_inapplicable_without_degradation(self) -> None:
        class SecFactsOnly:
            fidelity = "real"

            @staticmethod
            def supports_request(capability: str) -> bool:
                return capability != "price_history"

            def symbol_resolve(self, _company_name: str):
                raise AssertionError("inapplicable price request must not resolve a symbol")

            def financial_indicators(self, *_args: object, **_kwargs: object):
                raise AssertionError("not requested")

            def price_history(self, *_args: object, **_kwargs: object):
                raise AssertionError("inapplicable price request must not execute")

        researcher = ResearcherAgent(structured_data_provider=SecFactsOnly())
        question = SubQuestion(
            id="market",
            question="Alibaba share price",
            search_queries=[],
            structured_data_requests=[StructuredDataRequest(
                capability="price_history", company_name="Alibaba",
                start_date=date(2024, 1, 2), end_date=date(2024, 1, 3),
            )],
        )

        evidence, stats, resolutions = researcher.structured_evidence("run", question)

        self.assertEqual((evidence, resolutions), ([], []))
        self.assertEqual(stats["inapplicable_requests"], 1)
        self.assertEqual(stats["execution_failures"], 0)
        self.assertEqual(stats["executed_requests"], 0)

    def test_akshare_retry_is_not_queued_behind_a_timed_out_call(self) -> None:
        calls = multiprocessing.Value("i", 0)

        def first_call_hangs_then_returns() -> str:
            with calls.get_lock():
                calls.value += 1
                call_number = calls.value
            if call_number == 1:
                time.sleep(0.1)
            return "available"

        provider = AKShareStructuredDataProvider(
            akshare_module=object(),
            timeout_seconds=0.01,
            max_retries=1,
            sleep_func=lambda _: None,
        )

        self.assertEqual(provider._call(first_call_hangs_then_returns, "probe"), "available")
        self.assertEqual(calls.value, 2)

    def test_akshare_timeout_terminates_every_blocked_worker(self) -> None:
        provider = AKShareStructuredDataProvider(
            akshare_module=object(),
            timeout_seconds=0.01,
            max_retries=0,
        )
        baseline = {process.pid for process in multiprocessing.active_children()}

        def block_forever() -> None:
            while True:
                time.sleep(1)

        started = time.monotonic()
        for _ in range(20):
            with self.assertRaisesRegex(Exception, "timeout after"):
                provider._call(block_forever, "probe")
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 10.2)
        self.assertEqual(
            baseline,
            {process.pid for process in multiprocessing.active_children()},
        )

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
            isolate_processes=False,
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

        provider = AKShareStructuredDataProvider(
            akshare_module=AKShareStub(), isolate_processes=False
        )
        records = provider.financial_indicators("300750", metrics=["营业收入"])

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].entity, "300750")
        self.assertEqual(records[0].period, "20241231")

    def test_akshare_metric_units_are_metadata_driven_and_unknown_is_explicit(self) -> None:
        class Frame:
            def to_dict(self, _orient: str) -> list[dict[str, object]]:
                return [
                    {"指标": "营业收入", "20241231": 100.0},
                    {"指标": "毛利率", "20241231": 50.0},
                    {"指标": "每股收益", "20241231": 2.5},
                    {"指标": "市盈率", "20241231": 12.0},
                    {"指标": "存货周转率", "20241231": 3.0},
                    {"指标": "未知指标", "20241231": 1.0},
                ]

        class AKShareStub:
            def stock_financial_abstract(self, *, symbol: str) -> Frame:
                return Frame()

        provider = AKShareStructuredDataProvider(
            akshare_module=AKShareStub(), isolate_processes=False
        )
        records = provider.financial_indicators(
            "300750",
            metrics=["营业收入", "毛利率", "每股收益", "市盈率", "存货周转率", "未知指标"],
        )

        self.assertEqual(
            {record.metric_name: record.unit for record in records},
            {
                "营业收入": "元",
                "毛利率": "%",
                "每股收益": "元/股",
                "市盈率": "倍",
                "存货周转率": "次",
                "未知指标": "unknown",
            },
        )

    def test_akshare_symbol_resolution_requires_one_exact_identity(self) -> None:
        class Frame:
            def to_dict(self, _orient: str) -> list[dict[str, object]]:
                return [
                    {"code": "000001", "name": "平安银行"},
                    {"code": "601318", "name": "中国平安"},
                    {"code": "000002", "name": "平安"},
                    {"code": "000003", "name": "平安"},
                ]

        class AKShareStub:
            def stock_info_a_code_name(self) -> Frame:
                return Frame()

        provider = AKShareStructuredDataProvider(
            akshare_module=AKShareStub(), max_retries=0, isolate_processes=False
        )

        self.assertEqual(provider.symbol_resolve("601318").name, "中国平安")
        self.assertEqual(provider.symbol_resolve("平安银行").symbol, "000001")
        self.assertIsNone(provider.symbol_resolve("平安"))
        self.assertIsNone(provider.symbol_resolve("平安银"))

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

    def test_factory_selects_sec_companyfacts_provider(self) -> None:
        provider = build_structured_data_provider(
            {"DEEPRESEARCH_STRUCTURED_DATA_PROVIDER": "sec_companyfacts"}
        )
        try:
            self.assertIsInstance(provider, SecCompanyFactsProvider)
        finally:
            provider.close()

    def test_live_factory_explains_missing_optional_dependency(self) -> None:
        with mock.patch(
            "deepresearch_agent.tools.structured_data_factory.AKShareStructuredDataProvider",
            side_effect=ModuleNotFoundError(name="akshare"),
        ):
            with self.assertRaisesRegex(
                OptionalProviderDependencyError,
                r'\.\[finance\].*STRUCTURED_DATA_PROVIDER=fixture',
            ):
                build_structured_data_provider(
                    {"DEEPRESEARCH_STRUCTURED_DATA_PROVIDER": "akshare"}
                )

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

    def test_zero_record_execution_records_explicit_degradation(self) -> None:
        class EmptyFinancialProvider(FixtureStructuredDataProvider):
            def financial_indicators(
                self,
                symbol: str,
                periods: list[str] | None = None,
                metrics: list[str] | None = None,
            ) -> list[object]:
                return []

        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    structured_logging_enabled=False,
                ),
                structured_data_provider=EmptyFinancialProvider(),
            )
            state = engine.run(topic="宁德时代（300750）2024 年营业收入是多少", depth_level=1)
            engine._checkpoint_conn.close()

        event = next(
            item
            for item in state.metadata["degradation_events"]
            if item["reason"] == "structured_data_empty_result"
        )
        self.assertEqual(event["capability"], "financial_indicators")
        self.assertEqual(event["symbol"], "300750")
        self.assertEqual(event["periods"], ["20241231"])
        self.assertEqual(event["metrics"], ["营业收入"])

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
