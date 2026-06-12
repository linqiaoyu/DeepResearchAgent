from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.agents import ResearcherAgent
from deepresearch_agent.schemas import Evidence, StructuredDataRequest, SubQuestion
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.tools import FixtureStructuredDataProvider, build_structured_data_provider


class StructuredDataProviderTests(unittest.TestCase):
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
                source_url="akshare://financial_indicators/300750/20241231/归母净利润",
                source_title="AKShare financial_indicators 300750 20241231 归母净利润",
                source_pub_date=record.as_of,
                extract_text="宁德时代|归母净利润|20241231|累计|50744680000.0|元",
                structured_record=record,
            )

            store.add_evidence_many([evidence])
            loaded = store.list_evidence("run-1")[0]

        self.assertEqual(loaded.source_kind, "structured")
        self.assertIsNotNone(loaded.structured_record)
        self.assertEqual(loaded.structured_record.metric_name, "归母净利润")

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

        evidence = researcher.structured_evidence("run-1", sub_question)

        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].source_kind, "structured")
        self.assertEqual(evidence[0].claim_type, "data")
        self.assertIsNotNone(evidence[0].structured_record)
        self.assertEqual(evidence[0].structured_record.metric_name, "归母净利润")
        self.assertEqual(researcher.last_structured_stats["records"], 1)


if __name__ == "__main__":
    unittest.main()
