from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.tools.contracts import DegradationEvent, ToolErrorKind
from deepresearch_agent.tools.tavily_search import TavilySearchError, TavilySearchProvider


class FakeResponse:
    status_code = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class FakeHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = 0

    def post(self, *_: object, **__: object) -> FakeResponse:
        self.calls += 1
        return self.response

    def get(self, *_: object, **__: object) -> FakeResponse:
        return self.response


def _provider(ledger: Path, **kwargs: object) -> TavilySearchProvider:
    response = FakeResponse(
        {"results": [{"title": "t", "url": "https://e.test", "content": "c", "score": 0.9}]}
    )
    return TavilySearchProvider(
        "test-key",
        client=FakeHttpClient(response),
        ledger_path=ledger,
        max_retries=0,
        **kwargs,  # type: ignore[arg-type]
    )


class SearchCreditBudgetTests(unittest.TestCase):
    """R094: the credit gate bounds a run, not the project's whole history."""

    def test_a_spent_history_does_not_refuse_a_new_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "search.jsonl"
            # A previous run that used the entire cap, exactly the state the
            # real ledger was in: cumulative 520 against a 520 threshold.
            ledger.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "provider": "tavily",
                            "budget_id": "an-earlier-run",
                            "credit_estimate": 1,
                            "refused": False,
                        }
                    )
                    for _ in range(520)
                )
                + "\n",
                encoding="utf-8",
            )

            provider = _provider(ledger, credit_hard_threshold=30)
            sources = provider.search("蔚来 2024 年报 营业收入", top_k=1)

            self.assertEqual(len(sources), 1)
            rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertFalse(rows[-1]["refused"])
            self.assertEqual(rows[-1]["budget_id"], provider.budget_id)

    def test_the_run_budget_still_stops_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "search.jsonl"
            provider = _provider(ledger, credit_hard_threshold=2)

            provider.search("one", top_k=1)
            provider.search("two", top_k=1)
            with self.assertRaises(TavilySearchError):
                provider.search("three", top_k=1)

            rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[-1]["error_type"], "credit_hard_threshold")
            self.assertTrue(rows[-1]["refused"])

    def test_a_refusal_names_itself(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "search.jsonl"
            provider = _provider(ledger, credit_hard_threshold=0)

            with self.assertRaises(TavilySearchError) as caught:
                provider.search("blocked", top_k=1)

            refused_by = getattr(caught.exception, "refused_by", None)
            self.assertIsNotNone(refused_by)
            self.assertIn("own_credit_guardrail", refused_by or "")
            self.assertIn("threshold=0", refused_by or "")

    def test_a_degradation_event_can_carry_the_refusal_identity(self) -> None:
        """Without this the manifest reads a self-refusal as a provider outage."""

        event = DegradationEvent(
            tool="web_search",
            reason=ToolErrorKind.PERMANENT,
            impact="search results unavailable",
            attempts=1,
            refused_by="own_credit_guardrail:tavily:used=30:threshold=30",
        )

        self.assertIn("own_credit_guardrail", event.refused_by or "")


if __name__ == "__main__":
    unittest.main()
