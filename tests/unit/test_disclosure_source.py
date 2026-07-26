from __future__ import annotations

import unittest
from unittest import mock
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from deepresearch_agent.schemas import ResearchState, StructuredDataRequest, SubQuestion
from deepresearch_agent.tools import (
    CapabilityMetadata,
    CapabilityRegistry,
    CninfoDisclosureSource,
    DisclosureSourceError,
    FixtureSearchTool,
    FixtureStructuredDataProvider,
    ReliableToolExecutor,
    RunToolContext,
    build_capability_registry,
)
from deepresearch_agent.tools.capability_selector import DeterministicCapabilitySelector
from deepresearch_agent.tools.disclosure_source import (
    CNINFO_QUERY_ENDPOINT,
    CNINFO_STOCK_ENDPOINT,
    DISCLOSURE_TOOL_SPEC,
    cninfo_exchange_for_security_code,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine

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
    def test_disclosure_aggregate_timeout_covers_serial_http_envelope(
        self,
    ) -> None:
        self.assertEqual(DISCLOSURE_TOOL_SPEC.timeout_s, 120.0)
        self.assertGreater(
            DISCLOSURE_TOOL_SPEC.timeout_s,
            30.0 * 3,
        )

    def test_serial_disclosure_attempt_does_not_overlap_at_old_timeout(
        self,
    ) -> None:
        observed_timeouts: list[float] = []

        def simulated_slow_call(operation: Any, timeout_s: float) -> Any:
            observed_timeouts.append(timeout_s)
            if timeout_s <= 31.0:
                raise TimeoutError("simulated serial request exceeded 30s")
            return operation()

        with mock.patch.object(
            ReliableToolExecutor,
            "_call_with_timeout",
            side_effect=simulated_slow_call,
        ):
            sources = CninfoDisclosureSource(
                client=Client(security_code="600519"),
                max_results=1,
            ).search(
                "600519",
                "年度报告",
                date(2025, 1, 1),
                date(2026, 7, 26),
            )

        self.assertEqual(len(sources), 1)
        self.assertEqual(observed_timeouts, [120.0])

    def test_pdf_timeout_is_retried_as_transient(self) -> None:
        class FirstPdfTimeoutClient(Client):
            def __init__(self) -> None:
                super().__init__(security_code="600519")
                self.pdf_attempts = 0

            def get(self, url: str, **kwargs: Any) -> Response:
                if url != CNINFO_STOCK_ENDPOINT:
                    self.calls.append(("GET", url, kwargs))
                    self.pdf_attempts += 1
                    if self.pdf_attempts == 1:
                        raise httpx.ReadTimeout("first PDF attempt")
                    return Response(content=PDF)
                return super().get(url, **kwargs)

        client = FirstPdfTimeoutClient()
        context = RunToolContext.for_run()
        sources = CninfoDisclosureSource(
            client=client,
            context=context,
            max_results=1,
        ).search(
            "600519",
            "年度报告",
            date(2025, 1, 1),
            date(2026, 7, 26),
        )
        snapshot = context.external_request_budget.snapshot()

        self.assertEqual(len(sources), 1)
        self.assertEqual(client.pdf_attempts, 2)
        self.assertEqual(snapshot["authority_search_requests"], 2)
        self.assertEqual(snapshot["authority_fetch_requests"], 4)

    def test_disclosure_lane_survives_exhausted_web_fetch_budget(self) -> None:
        context = RunToolContext.for_run(max_external_fetch_requests=1)
        context.consume_external_request("fetch", tool="tavily_search")
        client = Client(security_code="600519")

        sources = CninfoDisclosureSource(
            client=client,
            context=context,
            max_results=1,
        ).search(
            "600519",
            "年度报告",
            date(2024, 1, 1),
            date(2026, 7, 25),
        )
        snapshot = context.external_request_budget.snapshot()

        self.assertEqual(len(sources), 1)
        self.assertEqual(snapshot["fetch_requests"], 1)
        self.assertEqual(snapshot["max_fetch_requests"], 1)
        self.assertEqual(snapshot["authority_search_requests"], 1)
        self.assertEqual(snapshot["authority_fetch_requests"], 2)
        self.assertEqual(
            snapshot["accepted_by_tool"]["disclosure_source"],
            {"search": 1, "fetch": 2},
        )

    def test_disclosure_budget_refusal_preserves_actionable_reason(self) -> None:
        context = RunToolContext.for_run(
            max_authority_fetch_requests=0,
        )

        with self.assertRaisesRegex(
            DisclosureSourceError,
            "budget exhausted for disclosure_source",
        ):
            CninfoDisclosureSource(
                client=Client(security_code="600519"),
                context=context,
                max_results=1,
            ).search(
                "600519",
                "年度报告",
                date(2024, 1, 1),
                date(2026, 7, 25),
            )

    def test_llm_engine_wires_default_cninfo_source_to_researcher(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch(
            "deepresearch_agent.workflow.engine.LLMClient"
        ):
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path("test.db"),
                    execution_mode="llm",
                    config_fail_fast_enabled=False,
                )
            )
            try:
                self.assertIs(
                    engine.researcher.disclosure_source,
                    engine.capability_registry.resolve("disclosure_source"),
                )
            finally:
                engine._checkpoint_conn.close()

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

    def test_annual_report_query_fetches_only_full_chinese_report(self) -> None:
        class AnnualReportClient(Client):
            def post(self, url: str, **kwargs: Any) -> Response:
                self.calls.append(("POST", url, kwargs))
                titles = [
                    ("贵州茅台2025年年度报告", "annual.PDF"),
                    ("贵州茅台2025年年度报告（英文版）", "annual-en.PDF"),
                    ("贵州茅台2025年年度报告摘要", "summary.PDF"),
                    ("贵州茅台2025年半年度报告", "half-year.PDF"),
                    ("贵州茅台2025年半年度报告摘要", "half-year-summary.PDF"),
                ]
                return Response(
                    {
                        "announcements": [
                            {
                                "secCode": "600519",
                                "announcementTitle": title,
                                "announcementTime": 1_765_843_200_000,
                                "adjunctUrl": path,
                            }
                            for title, path in titles
                        ]
                    }
                )

        client = AnnualReportClient(security_code="600519")
        sources = CninfoDisclosureSource(
            client=client,
            max_results=5,
        ).search(
            "600519",
            "年度报告",
            date(2025, 1, 1),
            date(2026, 7, 26),
        )
        pdf_gets = [
            url
            for method, url, _kwargs in client.calls
            if method == "GET" and url != CNINFO_STOCK_ENDPOINT
        ]

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].title, "贵州茅台2025年年度报告")
        self.assertEqual(pdf_gets, ["https://static.cninfo.com.cn/annual.PDF"])

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
