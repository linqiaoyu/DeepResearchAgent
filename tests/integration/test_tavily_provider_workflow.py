from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from typing import Any

from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.tools.tavily_search import TAVILY_SEARCH_ENDPOINT, TavilySearchProvider
from deepresearch_agent.workflow import DeepResearchEngine


class FakeTavilyResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.raise_called = False

    def raise_for_status(self) -> None:
        self.raise_called = True

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeTavilyClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[FakeTavilyResponse] = []
        self.failures_before_success = 0

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> FakeTavilyResponse:
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise RuntimeError("temporary Tavily failure")
        call_index = len(self.calls) + 1
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        query = json["query"]
        response = FakeTavilyResponse(
            {
                "results": [
                    {
                        "title": f"Tavily fake source {call_index}",
                        "url": f"https://tavily.test/source/{call_index}",
                        "content": (
                            f"AI agent adoption reached 42% in controlled finance workflows for {query}. "
                            "However risk and compliance constraints require citation checks and human oversight. "
                            "Evaluation teams should track citation accuracy, cost, latency, and token usage."
                        ),
                        "score": 0.91,
                        "published_date": "2026-05-20",
                    }
                ]
            }
        )
        self.responses.append(response)
        return response


class TavilyProviderWorkflowTests(unittest.TestCase):
    def test_engine_runs_with_tavily_adapter_and_fake_http_client(self) -> None:
        client = FakeTavilyClient()
        provider = TavilySearchProvider("test-key", client=client, timeout_seconds=2.0)

        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db", max_critic_iter=1)
            engine = DeepResearchEngine(
                settings=settings,
                store=SQLiteStore(settings.storage_path),
                search_tool=provider,
            )
            state = engine.run(topic="Tavily adapter workflow smoke", depth_level=1)

        self.assertEqual(state.status, "done")
        self.assertGreater(len(client.calls), 0)
        self.assertTrue(all(call["url"] == TAVILY_SEARCH_ENDPOINT for call in client.calls))
        self.assertTrue(all(call["headers"]["Authorization"] == "Bearer test-key" for call in client.calls))
        self.assertTrue(all(call["json"]["max_results"] == 1 for call in client.calls[:9]))
        self.assertTrue(all(response.raise_called for response in client.responses))

        self.assertGreater(len(state.sources), 0)
        self.assertTrue(all(source.id.startswith("tavily-") for source in state.sources))
        self.assertTrue(all(source.url.startswith("https://tavily.test/") for source in state.sources))
        self.assertGreater(len(state.evidence_store), 0)
        self.assertTrue(
            all(item.source_url.startswith("https://tavily.test/") for item in state.evidence_store)
        )
        self.assertIn("[^1]", state.final_report or "")

    def test_tavily_retries_and_records_search_ledger(self) -> None:
        client = FakeTavilyClient()
        client.failures_before_success = 1
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "search_ledger.jsonl"
            provider = TavilySearchProvider(
                "test-key",
                client=client,
                timeout_seconds=2.0,
                ledger_path=ledger_path,
                sleep_func=lambda _: None,
            )

            results = provider.search("retry query", top_k=1)
            rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(results), 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(rows[0]["provider"], "tavily")
        self.assertEqual(rows[0]["credit_estimate"], 1)
        self.assertTrue(rows[0]["success"])
        self.assertEqual(rows[0]["result_count"], 1)


if __name__ == "__main__":
    unittest.main()
