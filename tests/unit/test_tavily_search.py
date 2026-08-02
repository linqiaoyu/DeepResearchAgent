from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any

from deepresearch_agent.agents import ExtractorAgent, ReporterAgent
from deepresearch_agent.schemas import ResearchPlan, ResearchState, SubQuestion
from deepresearch_agent.tools import (
    ContractSearchProvider,
    ReliableToolExecutor,
    RetryBudget,
    RunToolContext,
    ToolErrorKind,
)
from deepresearch_agent.tools.tavily_search import (
    UNKNOWN_PUBLISHED_AT,
    TavilySearchProvider,
)

ROOT = Path(__file__).resolve().parents[2]
PDF_FIXTURE = ROOT / "tests" / "fixtures" / "catl_2022_070_excerpt.pdf"


class FakeResponse:
    def __init__(
        self,
        payload: Any,
        should_raise: bool = False,
        text: str = "",
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.should_raise = should_raise
        self.text = text
        self.content = content if content is not None else text.encode()
        self.headers = headers or {}
        self.raise_called = False

    def raise_for_status(self) -> None:
        self.raise_called = True
        if self.should_raise:
            raise RuntimeError("provider error")

    def json(self) -> Any:
        return self.payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> FakeResponse:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self.response

    def get(
        self,
        url: str,
        *,
        timeout: float,
        follow_redirects: bool,
    ) -> FakeResponse:
        self.get_calls.append(
            {
                "url": url,
                "timeout": timeout,
                "follow_redirects": follow_redirects,
            }
        )
        return self.response


class RaisingHttpClient:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> FakeResponse:
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        raise self.error


class TavilySearchProviderTests(unittest.TestCase):
    def test_fetch_stops_reading_at_policy_payload_limit(self) -> None:
        class StreamingResponse(FakeResponse):
            def __init__(self) -> None:
                super().__init__({}, headers={"content-type": "text/html"})
                self.read = 0

            @property
            def content(self) -> bytes:
                raise AssertionError("fetch must not materialize response.content")

            @content.setter
            def content(self, _value: bytes) -> None:
                pass

            def iter_bytes(self):
                for _ in range(100):
                    self.read += 1
                    yield b"x"

        response = StreamingResponse()
        provider = TavilySearchProvider(
            "test-key", client=FakeHttpClient(response), max_retries=0,
            raw_content_char_limit=25,
        )

        provider.fetch("https://example.test/page")

        self.assertLessEqual(response.read, 25)
    def _pdf_source(self, *, max_pages: int = 100):
        response = FakeResponse(
            {},
            content=PDF_FIXTURE.read_bytes(),
            headers={"content-type": "application/pdf"},
        )
        provider = TavilySearchProvider(
            "test-key",
            client=FakeHttpClient(response),
            pdf_max_pages=max_pages,
        )
        return provider.fetch("https://issuer.example/notice.pdf")

    def test_real_chinese_pdf_decodes_into_evidence(self) -> None:
        source = self._pdf_source()
        assert source is not None
        self.assertIn("[[PDF_PAGE=1]]", source.content)
        self.assertIn("宁德时代新能源科技股份有限公司", source.content)
        self.assertNotIn("\ufffd", source.content)
        evidence = ExtractorAgent().extract(
            "pdf-run",
            SubQuestion(id="q1", question="匈牙利项目", search_queries=[]),
            [source],
        )
        self.assertTrue(evidence)
        self.assertIn("宁德时代", evidence[0].extract_text)
        self.assertEqual(evidence[0].source_page, 1)

    def test_pdf_decode_failure_is_a_structured_permanent_error(self) -> None:
        response = FakeResponse(
            {},
            content=b"%PDF-1.7 broken",
            headers={"content-type": "application/pdf"},
        )
        provider = ContractSearchProvider(
            TavilySearchProvider("test-key", client=FakeHttpClient(response)),
            executor=ReliableToolExecutor(sleep=lambda _: None),
            context=RunToolContext(retry_budget=RetryBudget(max_retries=2)),
        )
        self.assertIsNone(provider.fetch("https://issuer.example/broken.pdf"))
        self.assertEqual(provider.degradation_events[0]["reason"], ToolErrorKind.PERMANENT)
        self.assertEqual(provider.degradation_events[0]["attempts"], 1)

    def test_pdf_page_limit_marks_source_and_evidence_truncated(self) -> None:
        source = self._pdf_source(max_pages=1)
        assert source is not None
        self.assertTrue(source.content_truncated)
        evidence = ExtractorAgent().extract(
            "pdf-truncated",
            SubQuestion(id="q1", question="匈牙利项目", search_queries=[]),
            [source],
        )
        self.assertTrue(evidence)
        self.assertTrue(all(item.content_truncated for item in evidence))

    def test_pdf_evidence_closes_report_footnote_mapping(self) -> None:
        source = self._pdf_source()
        assert source is not None
        sub_question = SubQuestion(id="q1", question="匈牙利项目", search_queries=[])
        state = ResearchState(
            research_id="pdf-footnote",
            topic="宁德时代匈牙利项目",
            plan=ResearchPlan(topic="宁德时代匈牙利项目", sub_questions=[sub_question]),
            evidence_store=ExtractorAgent().extract(
                "pdf-footnote",
                sub_question,
                [source],
            ),
        )
        state.final_report = ReporterAgent().report(state)
        self.assertTrue(state.report_footnote_evidence)
        self.assertTrue(
            set(state.report_footnote_evidence.values())
            <= {item.id for item in state.evidence_store}
        )
        self.assertEqual(len(state.report_footnote_evidence), 1)
        self.assertIn("[^1]", state.final_report)

    def test_fetch_hydrates_publisher_html_body(self) -> None:
        response = FakeResponse(
            {},
            text=(
                "<html><head><title>年度报告</title>"
                "<style>hidden</style></head><body>"
                "<script>ignored</script>营业收入 100 亿元</body></html>"
            ),
        )
        client = FakeHttpClient(response)
        with tempfile.TemporaryDirectory() as tmp:
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                ledger_path=Path(tmp) / "search_ledger.jsonl",
            )

            source = provider.fetch("https://issuer.example/report")

        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual(source.title, "年度报告")
        self.assertEqual(source.content, "年度报告\n营业收入 100 亿元")
        self.assertEqual(source.source_type, "web_fetch")
        self.assertEqual(len(client.get_calls), 1)

    def test_article_extraction_removes_navigation_without_dropping_numeric_financial_text(self) -> None:
        provider = TavilySearchProvider("test-key", client=FakeHttpClient(FakeResponse({})))
        text = provider._article_text(
            "<header>中华网 首页 友情链接 ICP备案</header><article>"
            "实现营业总收入661.43亿元，同比增长17.64%</article>"
            "<footer>点赞 评论 收藏 分享 举报纠错</footer>"
        )
        self.assertIn("实现营业总收入661.43亿元，同比增长17.64%", text)
        self.assertNotIn("友情链接", text)
        self.assertNotIn("点赞", text)

    def test_fetch_rejects_semantic_error_page_returned_as_http_success(self) -> None:
        response = FakeResponse(
            {},
            text=("<title>403 - Operations too frequent</title>"
                  "Page not found, please try again later. Take me home "
                  "Services by Moomoo Technologies Inc."),
            headers={"content-type": "text/html"},
        )
        provider = TavilySearchProvider("test-key", client=FakeHttpClient(response), max_retries=0)
        self.assertIsNone(provider.fetch("https://www.moomoo.com/403"))
        self.assertEqual(provider.last_error_type, "error_page_refused")

    def test_fetch_preserves_numeric_financial_page(self) -> None:
        response = FakeResponse(
            {},
            text="<title>业绩公告</title><article>实现营业总收入661.43亿元，同比增长17.64%</article>",
            headers={"content-type": "text/html"},
        )
        provider = TavilySearchProvider("test-key", client=FakeHttpClient(response), max_retries=0)
        self.assertIsNotNone(provider.fetch("https://issuer.example/earnings"))

    def test_relative_redirect_result_is_discarded_and_absolute_target_is_resolved(self) -> None:
        provider = TavilySearchProvider("test-key", client=FakeHttpClient(FakeResponse({})))
        self.assertIsNone(provider._normalise_source_url("/goto?opaque=1"))
        self.assertEqual(
            provider._normalise_source_url("/goto?url=https%3A%2F%2Fissuer.example%2Freport"),
            "https://issuer.example/report",
        )

    def test_search_posts_expected_request_and_normalizes_sources(self) -> None:
        response = FakeResponse(
            {
                "results": [
                    {
                        "title": "AI wealth source",
                        "url": "https://example.com/wealth-ai",
                        "content": "Snippet about AI wealth management.",
                        "raw_content": "Longer source text about AI wealth management.",
                        "score": 0.93456,
                        "published_date": "2026-05-20",
                    }
                ]
            }
        )
        client = FakeHttpClient(response)
        with tempfile.TemporaryDirectory() as tmp:
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                timeout_seconds=3.5,
                ledger_path=Path(tmp) / "search_ledger.jsonl",
            )

            sources = provider.search("AI wealth management", top_k=2, source_type="news")

        self.assertEqual(len(sources), 1)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(call["json"]["query"], "AI wealth management")
        self.assertEqual(call["json"]["max_results"], 2)
        self.assertEqual(call["json"]["topic"], "news")
        self.assertFalse(call["json"]["include_answer"])
        self.assertFalse(call["json"]["include_raw_content"])
        self.assertEqual(call["timeout"], 3.5)
        self.assertTrue(response.raise_called)

        source = sources[0]
        self.assertTrue(source.id.startswith("tavily-"))
        self.assertEqual(source.title, "AI wealth source")
        self.assertEqual(source.url, "https://example.com/wealth-ai")
        self.assertEqual(source.source_type, "news")
        self.assertEqual(source.published_at, date(2026, 5, 20))
        self.assertEqual(source.content, "Longer source text about AI wealth management.")
        self.assertEqual(source.credibility, 0.935)

    def test_missing_optional_fields_use_deterministic_fallbacks(self) -> None:
        response = FakeResponse(
            {
                "results": [
                    {
                        "title": "",
                        "url": "https://example.com/missing-fields",
                        "content": "",
                        "score": "not-a-number",
                    },
                    {
                        "title": "No URL",
                        "content": "This result is skipped because it has no URL.",
                    },
                ]
            }
        )
        client = FakeHttpClient(response)
        with tempfile.TemporaryDirectory() as tmp:
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                ledger_path=Path(tmp) / "search_ledger.jsonl",
            )

            sources = provider.search("missing fields", top_k=5, source_type="official")

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].title, "https://example.com/missing-fields")
        self.assertEqual(sources[0].source_type, "web")
        self.assertEqual(sources[0].published_at, UNKNOWN_PUBLISHED_AT)
        self.assertEqual(sources[0].content, "https://example.com/missing-fields")
        self.assertEqual(sources[0].credibility, 0.75)

    def test_empty_top_k_does_not_call_client(self) -> None:
        client = FakeHttpClient(FakeResponse({"results": []}))
        with tempfile.TemporaryDirectory() as tmp:
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                ledger_path=Path(tmp) / "search_ledger.jsonl",
            )

            self.assertEqual(provider.search("skip", top_k=0), [])
        self.assertEqual(client.calls, [])

    def test_http_errors_degrade_to_empty_result(self) -> None:
        client = FakeHttpClient(FakeResponse({"results": []}, should_raise=True))
        with tempfile.TemporaryDirectory() as tmp:
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                ledger_path=Path(tmp) / "search_ledger.jsonl",
            )

            self.assertEqual(provider.search("fail"), [])
            self.assertEqual(provider.last_error_type, "RuntimeError")

    def test_client_errors_degrade_to_empty_result(self) -> None:
        client = RaisingHttpClient(TimeoutError("timed out"))
        with tempfile.TemporaryDirectory() as tmp:
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                ledger_path=Path(tmp) / "search_ledger.jsonl",
            )

            self.assertEqual(provider.search("slow query"), [])
            self.assertEqual(provider.last_error_type, "TimeoutError")

    def test_non_object_json_degrades_to_empty_result(self) -> None:
        client = FakeHttpClient(FakeResponse(["not", "an", "object"]))
        with tempfile.TemporaryDirectory() as tmp:
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                ledger_path=Path(tmp) / "search_ledger.jsonl",
            )

            self.assertEqual(provider.search("bad json"), [])
            self.assertEqual(provider.last_error_type, "ValueError")

    def test_raw_content_is_capped_per_source(self) -> None:
        response = FakeResponse(
            {
                "results": [
                    {
                        "title": "Large source",
                        "url": "https://example.com/large",
                        "raw_content": "abcdef",
                    }
                ]
            }
        )
        client = FakeHttpClient(response)
        with tempfile.TemporaryDirectory() as tmp:
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                raw_content_char_limit=3,
                ledger_path=Path(tmp) / "search_ledger.jsonl",
            )

            sources = provider.search("large source", top_k=1)

        self.assertEqual(sources[0].content, "abc")

    def test_warning_threshold_marks_live_call_without_refusing(self) -> None:
        response = FakeResponse(
            {
                "results": [
                    {
                        "title": "Threshold source",
                        "url": "https://example.com/threshold",
                        "content": "Threshold content.",
                    }
                ]
            }
        )
        client = FakeHttpClient(response)
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "search_ledger.jsonl"
            ledger_path.write_text(
                json.dumps({"credit_estimate": 449, "refused": False}) + "\n",
                encoding="utf-8",
            )
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                ledger_path=ledger_path,
                credit_warning_threshold=450,
                credit_hard_threshold=520,
            )

            sources = provider.search("threshold", top_k=1)
            rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(sources), 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(rows[-1]["credit_estimate"], 1)
        self.assertFalse(rows[-1]["refused"])
        self.assertTrue(rows[-1]["guardrail_warning"])

    def test_hard_threshold_refuses_without_credit_or_client_call(self) -> None:
        client = FakeHttpClient(FakeResponse({"results": []}))
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "search_ledger.jsonl"
            ledger_path.write_text(
                json.dumps({"credit_estimate": 520, "refused": False}) + "\n",
                encoding="utf-8",
            )
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                ledger_path=ledger_path,
                credit_warning_threshold=450,
                credit_hard_threshold=520,
            )

            with self.assertRaisesRegex(RuntimeError, "hard threshold"):
                provider.search("blocked", top_k=1)
            rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(client.calls, [])
        self.assertEqual(rows[-1]["credit_estimate"], 0)
        self.assertTrue(rows[-1]["refused"])
        self.assertEqual(rows[-1]["error_type"], "credit_hard_threshold")

    def test_refused_rows_do_not_count_toward_guardrail_total(self) -> None:
        response = FakeResponse(
            {
                "results": [
                    {
                        "title": "Clean source",
                        "url": "https://example.com/clean",
                        "content": "Clean content.",
                    }
                ]
            }
        )
        client = FakeHttpClient(response)
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "search_ledger.jsonl"
            ledger_path.write_text(
                "\n".join(
                    [
                        json.dumps({"credit_estimate": 520, "refused": True}),
                        json.dumps({"credit_estimate": 1, "refused": False}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                ledger_path=ledger_path,
                credit_warning_threshold=450,
                credit_hard_threshold=520,
            )

            sources = provider.search("clean", top_k=1)

        self.assertEqual(len(sources), 1)
        self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
