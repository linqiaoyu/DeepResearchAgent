from __future__ import annotations

import json
import unittest
from decimal import Decimal
from pathlib import Path

import httpx

from deepresearch_agent.schemas import ResearchState, SubQuestion
from deepresearch_agent.tools import (
    DeterministicCapabilitySelector,
    FixtureSearchTool,
    FixtureStructuredDataProvider,
    SecCompanyFactsProvider,
    StructuredDataUnsupportedMetric,
    build_capability_registry,
)
from deepresearch_agent.tools.capability_selector import classify_subquestion


_FIXTURE = Path(__file__).parents[1] / "fixtures" / "sec_companyfacts_nio_fy2024.json"


def _nio_provider() -> SecCompanyFactsProvider:
    payload = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/files/company_tickers.json":
            return httpx.Response(200, json={"0": {
                "cik_str": 1736541, "ticker": "NIO", "title": "NIO Inc.",
            }})
        if request.url.path.endswith("CIK0001736541.json"):
            return httpx.Response(200, json=payload)
        return httpx.Response(404)

    return SecCompanyFactsProvider(
        client=httpx.Client(transport=httpx.MockTransport(handler)), max_retries=0
    )


class Round083StructuredDataTests(unittest.TestCase):
    def test_selects_later_revenue_concept_when_first_has_no_requested_fact(self) -> None:
        records = _nio_provider().financial_indicators(
            "CIK0001736541", periods=["20241231"], metrics=["营业收入"]
        )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].value, Decimal("65731559000"))
        self.assertEqual(records[0].unit, "CNY")

    def test_gross_profit_is_mapped_and_ratio_metrics_are_explicitly_unsupported(self) -> None:
        provider = _nio_provider()
        gross = provider.financial_indicators(
            "CIK0001736541", periods=["20241231"], metrics=["毛利"]
        )

        self.assertEqual([(item.value, item.unit) for item in gross], [(Decimal("6492762000"), "CNY")])
        for metric in ("毛利率", "市盈率"):
            with self.subTest(metric=metric):
                with self.assertRaises(StructuredDataUnsupportedMetric):
                    provider.financial_indicators(
                        "CIK0001736541", periods=["20241231"], metrics=[metric]
                    )

    def test_mapped_metric_without_requested_period_is_an_empty_result(self) -> None:
        records = _nio_provider().financial_indicators(
            "CIK0001736541", periods=["20151231"], metrics=["营业收入"]
        )

        self.assertEqual(records, [])

    def test_english_and_chinese_financial_intent_select_structured_data(self) -> None:
        selector = DeterministicCapabilitySelector(build_capability_registry(
            search_provider=FixtureSearchTool(),
            structured_data_provider=FixtureStructuredDataProvider(),
        ))
        english = SubQuestion(
            id="english", question="PDD 2024 annual report revenue and gross margin",
            search_queries=[],
        )
        chinese = SubQuestion(
            id="chinese", question="蔚来 2024 年年报的营收与毛利情况", search_queries=[],
        )
        narrative = SubQuestion(id="narrative", question="How does the market work?", search_queries=[])

        self.assertEqual(classify_subquestion(english), "financial_metric")
        self.assertNotIn(
            "structured_data_provider",
            selector.select(ResearchState(topic="test"), english).rejected_capabilities,
        )
        self.assertEqual(classify_subquestion(chinese), "financial_metric")
        self.assertNotIn(
            "structured_data_provider",
            selector.select(ResearchState(topic="test"), chinese).rejected_capabilities,
        )
        self.assertEqual(classify_subquestion(narrative), "narrative")
        self.assertIn(
            "structured_data_provider",
            selector.select(ResearchState(topic="test"), narrative).rejected_capabilities,
        )
