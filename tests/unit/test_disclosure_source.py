from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from typing import Any

from deepresearch_agent.schemas import ResearchState, StructuredDataRequest, SubQuestion
from deepresearch_agent.tools import (
    CapabilityMetadata,
    CapabilityRegistry,
    CninfoDisclosureSource,
    DisclosureSourceError,
    FixtureSearchTool,
    FixtureStructuredDataProvider,
    build_capability_registry,
)
from deepresearch_agent.tools.capability_selector import DeterministicCapabilitySelector
from deepresearch_agent.tools.disclosure_source import (
    CNINFO_QUERY_ENDPOINT,
    CNINFO_STOCK_ENDPOINT,
    DISCLOSURE_TOOL_SPEC,
    cninfo_exchange_for_security_code,
)

ROOT = Path(__file__).resolve().parents[2]
PDF = (ROOT / "tests/fixtures/catl_2022_070_excerpt.pdf").read_bytes()


class Response:
    def __init__(self, payload: Any = None, content: bytes = b"") -> None:
        self.payload, self.content = payload, content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self.payload


class Client:
    def __init__(self, *, malformed: bool = False, security_code: str = "300750") -> None:
        self.malformed = malformed
        self.security_code = security_code
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> Response:
        self.calls.append(("GET", url, kwargs))
        if url == CNINFO_STOCK_ENDPOINT:
            return Response({"stockList": [{"code": self.security_code, "orgId": "GD165627"}]})
        return Response(content=PDF)

    def post(self, url: str, **kwargs: Any) -> Response:
        self.calls.append(("POST", url, kwargs))
        if self.malformed:
            return Response({"renamedAnnouncements": []})
        return Response(
            {
                "announcements": [
                    {
                        "secCode": self.security_code,
                        "announcementTitle": "关于投资建设<em>匈牙利</em>项目的公告",
                        "announcementTime": 1660320000000,
                        "adjunctUrl": "finalpage/2022-08-13/1214282839.PDF",
                    }
                ]
            }
        )


class DisclosureSourceTests(unittest.TestCase):
    def test_financial_intent_prefers_matching_pdf_pages(self) -> None:
        source = CninfoDisclosureSource(client=Client(), max_results=1).search(
            "300750", "匈牙利", date(2022, 1, 1), date(2026, 7, 25),
            preferred_terms=("宁德时代新能源科技股份有限公司",),
        )[0]

        self.assertIn("宁德时代新能源科技股份有限公司", source.content)
    def test_cninfo_query_decodes_primary_pdf_through_pypdf(self) -> None:
        client = Client()
        sources = CninfoDisclosureSource(client=client, max_results=1).search(
            "300750", "匈牙利", date(2022, 1, 1), date(2026, 7, 25)
        )

        self.assertEqual(len(sources), 1)
        source = sources[0]
        self.assertEqual(source.source_tier, "primary")
        self.assertEqual(source.published_at, date(2022, 8, 12))
        self.assertIn("宁德时代新能源科技股份有限公司", source.content)
        query = next(call for call in client.calls if call[1] == CNINFO_QUERY_ENDPOINT)
        self.assertEqual(query[2]["data"]["stock"], "300750,GD165627")
        self.assertEqual(query[2]["data"]["searchkey"], "匈牙利")

    def test_endpoint_contract_change_fails_closed(self) -> None:
        with self.assertRaisesRegex(DisclosureSourceError, "cninfo_contract_changed"):
            CninfoDisclosureSource(client=Client(malformed=True)).search(
                "300750", "匈牙利", date(2022, 1, 1), date(2026, 7, 25)
            )

    def test_security_code_maps_to_cninfo_exchange_without_defaulting_to_shenzhen(self) -> None:
        self.assertEqual(cninfo_exchange_for_security_code("600519"), ("sse", "sh"))
        self.assertEqual(cninfo_exchange_for_security_code("300750"), ("szse", "sz"))
        with self.assertRaisesRegex(ValueError, "only Shanghai and Shenzhen"):
            cninfo_exchange_for_security_code("430047")

    def test_shanghai_code_posts_shanghai_cninfo_parameters(self) -> None:
        client = Client(security_code="600519")
        CninfoDisclosureSource(client=client, max_results=1).search(
            "600519", "年度报告", date(2024, 1, 1), date(2026, 7, 25)
        )
        query = next(call for call in client.calls if call[1] == CNINFO_QUERY_ENDPOINT)
        self.assertEqual(query[2]["data"]["column"], "sse")
        self.assertEqual(query[2]["data"]["plate"], "sh")

    def test_financial_entity_prioritizes_registered_disclosure_capability(self) -> None:
        registry = build_capability_registry(
            search_provider=FixtureSearchTool(),
            structured_data_provider=FixtureStructuredDataProvider(),
            disclosure_source=object(),
        )
        state = ResearchState(topic="宁德时代匈牙利工厂")
        selection = DeterministicCapabilitySelector(registry).select(
            state,
            SubQuestion(
                id="q26",
                question="宁德时代（300750）匈牙利工厂时间线",
                search_queries=["匈牙利 投产"],
                structured_data_requests=[
                    StructuredDataRequest(
                        capability="financial_indicators",
                        company_name="宁德时代",
                    )
                ],
            ),
        )

        self.assertEqual(selection.selected_capabilities[0], "disclosure_source")
        self.assertIn("security code or company entity", selection.criterion)
        self.assertTrue(state.agent_decisions[0].criterion)
        self.assertEqual(registry.get("disclosure_source").tool_spec, DISCLOSURE_TOOL_SPEC)

    def test_registry_rejects_parallel_non_toolspec_metadata(self) -> None:
        registry = CapabilityRegistry()
        with self.assertRaises(ValueError):
            registry.register(
                CapabilityMetadata(
                    name="other_name",
                    applicable_subquestion_types=("event",),
                    cost_level="free",
                    has_side_effect=False,
                    tool_spec=DISCLOSURE_TOOL_SPEC,
                ),
                object(),
            )


if __name__ == "__main__":
    unittest.main()
