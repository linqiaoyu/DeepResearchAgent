from __future__ import annotations

import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from deepresearch_agent.schemas import (
    ResearchPlan,
    Source,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import (
    CninfoDisclosureSource,
    ReliableToolExecutor,
    RunToolContext,
    ToolErrorKind,
)
from deepresearch_agent.tools.disclosure_source import (
    CNINFO_QUERY_ENDPOINT,
    CNINFO_STOCK_ENDPOINT,
    DISCLOSURE_TOOL_SPEC,
)
from deepresearch_agent.workflow import DeepResearchEngine


class FaultResponse:
    def __init__(
        self,
        payload: Any = None,
        *,
        status_code: int = 200,
        url: str = CNINFO_QUERY_ENDPOINT,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.request = httpx.Request("GET", url)
        self.response = httpx.Response(
            status_code,
            request=self.request,
        )
        self.content = b""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=self.request,
                response=self.response,
            )

    def json(self) -> Any:
        return self.payload


class FaultClient:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.calls: list[tuple[str, str]] = []

    def get(self, url: str, **_kwargs: Any) -> FaultResponse:
        self.calls.append(("GET", url))
        request = httpx.Request("GET", url)
        if url == CNINFO_STOCK_ENDPOINT:
            if self.mode == "connection":
                raise httpx.ConnectError("connection refused", request=request)
            if self.mode == "timeout":
                raise httpx.ReadTimeout("read deadline", request=request)
            return FaultResponse(
                {"stockList": [{"code": "600519", "orgId": "gssh0600519"}]},
                url=url,
            )
        return FaultResponse({}, url=url)

    def post(self, url: str, **_kwargs: Any) -> FaultResponse:
        self.calls.append(("POST", url))
        if self.mode == "503":
            return FaultResponse(status_code=503, url=url)
        if self.mode == "404":
            return FaultResponse(status_code=404, url=url)
        if self.mode == "malformed":
            return FaultResponse({"renamedAnnouncements": []}, url=url)
        if self.mode == "invalid_entry":
            return FaultResponse(
                {
                    "announcements": [
                        {
                            "secCode": "600519",
                            "announcementTitle": "贵州茅台2025年年度报告",
                        }
                    ]
                },
                url=url,
            )
        if self.mode == "empty":
            return FaultResponse({"announcements": []}, url=url)
        raise AssertionError(f"unexpected mode reached announcement POST: {self.mode}")


class BlockingThenEmptyClient:
    """First stock lookup hangs; later calls return a valid empty response."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.first_returned = threading.Event()
        self.calls: list[tuple[str, str]] = []
        self._stock_calls = 0

    def get(self, url: str, **_kwargs: Any) -> FaultResponse:
        self.calls.append(("GET", url))
        if url != CNINFO_STOCK_ENDPOINT:
            raise AssertionError(f"unexpected PDF GET: {url}")
        self._stock_calls += 1
        if self._stock_calls == 1:
            self.entered.set()
            self.release.wait()
            self.first_returned.set()
        return FaultResponse(
            {"stockList": [{"code": "600519", "orgId": "gssh0600519"}]},
            url=url,
        )

    def post(self, url: str, **_kwargs: Any) -> FaultResponse:
        self.calls.append(("POST", url))
        return FaultResponse({"announcements": []}, url=url)


class WebFallbackProvider:
    search_counts_toward_budget = True

    def __init__(self) -> None:
        self.search_calls = 0
        self.fetch_calls = 0
        self.source = Source(
            id="fallback-web",
            title="贵州茅台公开网页资料",
            url="https://example.test/moutai-web",
            source_type="company_report",
            published_at=date(2026, 6, 1),
            content=(
                "贵州茅台公开网页资料说明营业收入信息仍需以年度报告原文复核。"
            ),
            credibility=0.7,
            source_tier="secondary",
        )

    def search(
        self,
        _query: str,
        top_k: int = 3,
        source_type: str | None = None,
        **_kwargs: object,
    ) -> list[Source]:
        del top_k, source_type
        self.search_calls += 1
        return [self.source]

    def fetch(self, url: str, **_kwargs: object) -> Source | None:
        self.fetch_calls += 1
        return self.source if url == self.source.url else None


class FinancialPlanner:
    last_stats: dict[str, object] = {}

    def plan(
        self,
        topic: str,
        depth_level: int = 1,
        research_id: str | None = None,
    ) -> ResearchPlan:
        del research_id
        return ResearchPlan(
            topic=topic,
            depth_level=depth_level,
            sub_questions=[
                SubQuestion(
                    id="financial_metric",
                    question="贵州茅台 600519 2025 年营业收入是多少？",
                    search_queries=["贵州茅台 600519 2025 营业收入"],
                    expected_source_types=["company_report"],
                    structured_data_requests=[
                        StructuredDataRequest(
                            capability="financial_indicators",
                            company_name="贵州茅台",
                            symbol="600519",
                            periods=["2025"],
                            metrics=["营业收入"],
                        )
                    ],
                )
            ],
        )


class DisclosureDegradationTests(unittest.TestCase):
    def _direct_failure(
        self,
        mode: str,
    ) -> tuple[CninfoDisclosureSource, RunToolContext, FaultClient]:
        context = RunToolContext.for_run(max_retries=20)
        client = FaultClient(mode)
        source = CninfoDisclosureSource(
            client=client,
            context=context,
            executor=ReliableToolExecutor(
                sleep=lambda _delay: None,
                random_source=lambda: 0.5,
            ),
        )
        result = source.search(
            "600519",
            "年度报告",
            date(2025, 1, 1),
            date(2026, 7, 26),
        )
        self.assertEqual(result, [])
        return source, context, client

    def test_connection_failure_retries_then_degrades(self) -> None:
        source, context, _client = self._direct_failure("connection")
        self.assertEqual(source.last_result.attempts, 3)
        self.assertEqual(
            context.degradation_events[-1].reason,
            ToolErrorKind.TRANSIENT,
        )
        self.assertEqual(
            context.external_request_budget.snapshot()["accepted_by_tool"]
            ["disclosure_source"],
            {"search": 0, "fetch": 3},
        )

    def test_timeout_retries_inside_total_deadline_then_degrades(self) -> None:
        source, context, _client = self._direct_failure("timeout")
        self.assertEqual(source.last_result.attempts, 3)
        self.assertLessEqual(
            source.last_result.elapsed_ms,
            120_000,
        )
        self.assertEqual(
            context.degradation_events[-1].reason,
            ToolErrorKind.TIMEOUT,
        )

    def test_blocked_cninfo_worker_is_quarantined_across_runs(self) -> None:
        client = BlockingThenEmptyClient()
        self.addCleanup(client.release.set)
        short_spec = DISCLOSURE_TOOL_SPEC.model_copy(
            update={"timeout_s": 0.03, "total_timeout_s": 0.03}
        )
        first_context = RunToolContext.for_run(max_retries=20)
        source = CninfoDisclosureSource(
            client=client,
            context=first_context,
            tool_spec=short_spec,
        )

        started = time.monotonic()
        first_result = source.search(
            "600519",
            "年度报告",
            date(2025, 1, 1),
            date(2026, 7, 26),
        )
        first_elapsed = time.monotonic() - started

        self.assertEqual(first_result, [])
        self.assertTrue(client.entered.is_set())
        self.assertLess(first_elapsed, 0.1)
        self.assertTrue(source.timed_out_operation_pending)
        self.assertEqual(source.last_result.attempts, 1)
        self.assertEqual(
            source.last_result.error.exception_type,
            "DetachedToolOperationError",
        )
        self.assertEqual(
            first_context.external_request_budget.snapshot()[
                "accepted_by_tool"
            ]["disclosure_source"],
            {"search": 0, "fetch": 1},
        )

        # Installing a new run context while the first worker is blocked must
        # fail fast: no second provider call and no budget charged to the new
        # run.  The old worker retains only its captured first-run context.
        second_context = RunToolContext.for_run(max_retries=20)
        source.set_run_context(second_context)
        second_result = source.search(
            "600519",
            "年度报告",
            date(2025, 1, 1),
            date(2026, 7, 26),
        )
        self.assertEqual(second_result, [])
        self.assertEqual(source.last_result.attempts, 0)
        self.assertEqual(client.calls, [("GET", CNINFO_STOCK_ENDPOINT)])
        self.assertEqual(
            second_context.external_request_budget.snapshot()[
                "total_fetch_requests"
            ],
            0,
        )
        self.assertEqual(
            second_context.external_request_budget.snapshot()[
                "total_search_requests"
            ],
            0,
        )

        # The original GET cannot be killed by Python.  Once the fake transport
        # returns, cooperative cancellation stops that detached worker before
        # its POST boundary, and the quarantine can safely clear.
        client.release.set()
        self.assertTrue(client.first_returned.wait(timeout=0.5))
        settle_deadline = time.monotonic() + 0.5
        while (
            source.timed_out_operation_pending
            and time.monotonic() < settle_deadline
        ):
            time.sleep(0.001)
        self.assertFalse(source.timed_out_operation_pending)
        self.assertEqual(client.calls, [("GET", CNINFO_STOCK_ENDPOINT)])
        self.assertEqual(
            second_context.external_request_budget.snapshot()[
                "total_fetch_requests"
            ],
            0,
        )

        # Reuse is allowed only after the detached worker has terminated; this
        # request is then charged solely to the second run.
        self.assertEqual(
            source.search(
                "600519",
                "年度报告",
                date(2025, 1, 1),
                date(2026, 7, 26),
            ),
            [],
        )
        self.assertEqual(
            client.calls,
            [
                ("GET", CNINFO_STOCK_ENDPOINT),
                ("GET", CNINFO_STOCK_ENDPOINT),
                ("POST", CNINFO_QUERY_ENDPOINT),
            ],
        )
        self.assertEqual(
            second_context.external_request_budget.snapshot()[
                "accepted_by_tool"
            ]["disclosure_source"],
            {"search": 1, "fetch": 1},
        )

    def test_503_retries_then_degrades(self) -> None:
        source, context, _client = self._direct_failure("503")
        self.assertEqual(source.last_result.attempts, 3)
        self.assertEqual(
            context.degradation_events[-1].reason,
            ToolErrorKind.TRANSIENT,
        )
        self.assertEqual(
            context.external_request_budget.snapshot()["accepted_by_tool"]
            ["disclosure_source"],
            {"search": 3, "fetch": 3},
        )

    def test_empty_announcements_are_visible_as_authority_not_found(self) -> None:
        source, context, _client = self._direct_failure("empty")
        self.assertEqual(source.last_result.attempts, 1)
        self.assertEqual(
            context.degradation_events[-1].reason,
            ToolErrorKind.NOT_FOUND,
        )
        self.assertIn(
            "no matching document",
            context.degradation_events[-1].impact,
        )

    def test_malformed_announcements_fail_closed_inside_authority(self) -> None:
        source, context, _client = self._direct_failure("malformed")
        self.assertEqual(source.last_result.attempts, 1)
        self.assertEqual(
            context.degradation_events[-1].reason,
            ToolErrorKind.PERMANENT,
        )

    def test_nonempty_invalid_announcement_entry_fails_closed(self) -> None:
        source, context, _client = self._direct_failure("invalid_entry")
        self.assertEqual(source.last_result.attempts, 1)
        self.assertEqual(
            context.degradation_events[-1].reason,
            ToolErrorKind.PERMANENT,
        )

    def test_404_is_not_retried(self) -> None:
        source, context, _client = self._direct_failure("404")
        self.assertEqual(source.last_result.attempts, 1)
        self.assertEqual(
            context.degradation_events[-1].reason,
            ToolErrorKind.NOT_FOUND,
        )

    def test_circuit_opens_after_degraded_calls_and_fast_fails(self) -> None:
        context = RunToolContext.for_run(max_retries=20)
        client = FaultClient("connection")
        source = CninfoDisclosureSource(
            client=client,
            context=context,
            executor=ReliableToolExecutor(
                sleep=lambda _delay: None,
                random_source=lambda: 0.5,
            ),
        )
        for _ in range(4):
            self.assertEqual(
                source.search(
                    "600519",
                    "年度报告",
                    date(2025, 1, 1),
                    date(2026, 7, 26),
                ),
                [],
            )

        self.assertEqual(source.last_result.attempts, 0)
        self.assertEqual(len(client.calls), 9)
        self.assertEqual(context.degradation_events[-1].attempts, 0)
        self.assertIn(
            "circuit is open",
            source.last_result.error.message,
        )

    def _pipeline_fallback(self, mode: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            web = WebFallbackProvider()
            disclosure = CninfoDisclosureSource(
                client=FaultClient(mode),
                executor=ReliableToolExecutor(
                    sleep=lambda _delay: None,
                    random_source=lambda: 0.5,
                ),
            )
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=root / "research.db",
                    runs_root=root / "runs",
                    as_of=date(2026, 7, 26),
                    structured_logging_enabled=False,
                    run_manifest_enabled=False,
                    max_critic_iter=1,
                ),
                search_tool=web,
                disclosure_source=disclosure,
            )
            engine.planner = FinancialPlanner()
            try:
                state = engine.run(
                    topic="贵州茅台 600519 2025 年营业收入研究",
                    depth_level=1,
                )
            finally:
                engine._checkpoint_conn.close()

        self.assertEqual(state.status, "done")
        self.assertGreater(web.search_calls, 0)
        self.assertGreater(web.fetch_calls, 0)
        self.assertNotIn("static.cninfo.com.cn", state.final_report or "")
        self.assertTrue(
            "## 数据获取降级" in (state.final_report or ""),
            "reader-visible degradation section absent",
        )
        self.assertTrue(
            "disclosure_source" in (state.final_report or ""),
            "reader-visible authority channel absent",
        )
        self.assertTrue(
            any(
                record.query.startswith("[disclosure]")
                for record in state.search_records
            )
        )

    def test_connection_failure_falls_back_to_web_and_is_visible(self) -> None:
        self._pipeline_fallback("connection")

    def test_timeout_falls_back_to_web_and_is_visible(self) -> None:
        self._pipeline_fallback("timeout")

    def test_503_falls_back_to_web_and_is_visible(self) -> None:
        self._pipeline_fallback("503")

    def test_empty_result_falls_back_to_web_and_is_visible(self) -> None:
        self._pipeline_fallback("empty")

    def test_malformed_result_falls_back_to_web_and_is_visible(self) -> None:
        self._pipeline_fallback("malformed")


if __name__ == "__main__":
    unittest.main()
