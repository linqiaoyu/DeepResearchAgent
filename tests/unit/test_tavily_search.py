from __future__ import annotations

import unittest
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from deepresearch_agent.tools.tavily_search import (
    UNKNOWN_PUBLISHED_AT,
    TavilySearchProvider,
)


class FakeResponse:
    def __init__(self, payload: Any, should_raise: bool = False) -> None:
        self.payload = payload
        self.should_raise = should_raise
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


if __name__ == "__main__":
    unittest.main()
