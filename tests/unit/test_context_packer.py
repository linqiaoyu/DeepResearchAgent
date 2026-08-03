from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.context import (
    ContextBudget,
    HeuristicTokenEstimator,
    build_token_estimator,
    pack_evidence,
)
from deepresearch_agent.schemas import Evidence
from deepresearch_agent.settings import Settings


class FixedEstimator:
    def __init__(self, tokens: int) -> None:
        self.tokens = tokens

    def estimate(self, text: str) -> int:
        return self.tokens


def evidence(
    item_id: str,
    *,
    url: str | None = None,
    text: str | None = None,
    confidence: float = 0.8,
) -> Evidence:
    body = text or f"AI agent evidence {item_id}"
    return Evidence(
        id=item_id,
        research_id="run-context",
        sub_question_id="q",
        claim=body,
        claim_type="fact",
        source_url=url or f"https://example.com/{item_id}",
        source_title=f"source {item_id}",
        source_pub_date=date(2026, 1, 1),
        extract_text=body,
        confidence=confidence,
    )


class ContextPackerTests(unittest.TestCase):
    def test_default_token_estimator_is_local_and_deterministic(self) -> None:
        self.assertIsInstance(build_token_estimator(), HeuristicTokenEstimator)

    def test_same_input_produces_same_output(self) -> None:
        items = [evidence("a"), evidence("b"), evidence("c")]
        kwargs = {
            "topic": "AI agent",
            "budget": 20,
            "as_of": date(2026, 1, 2),
            "estimator": FixedEstimator(10),
        }
        first = pack_evidence(items, **kwargs)
        second = pack_evidence(items, **kwargs)
        self.assertEqual(first.model_dump(), second.model_dump())

    def test_same_url_different_extracts_are_not_deduplicated(self) -> None:
        items = [
            evidence("a", url="HTTPS://EXAMPLE.COM/path/?b=2&a=1", text="first"),
            evidence("b", url="https://example.com/path?a=1&b=2#fragment", text="second"),
            evidence("c", url="https://other.example/c", text="first"),
        ]
        result = pack_evidence(
            items,
            topic="first",
            budget=100,
            estimator=FixedEstimator(10),
        )
        self.assertEqual(result.dropped, [])
        self.assertEqual([item.id for item in result.selected], ["a", "c", "b"])

    def test_same_normalized_url_and_extract_are_deduplicated(self) -> None:
        items = [
            evidence("a", url="HTTPS://EXAMPLE.COM/path/?b=2&a=1", text="same"),
            evidence("b", url="https://example.com/path?a=1&b=2#fragment", text="same"),
        ]
        result = pack_evidence(
            items,
            topic="same",
            budget=100,
            estimator=FixedEstimator(10),
        )
        self.assertEqual([item.id for item in result.selected], ["a"])
        self.assertEqual(
            [(item.evidence_id, item.reason) for item in result.dropped],
            [("b", "duplicate_content")],
        )

    def test_same_extract_from_different_urls_is_not_deduplicated(self) -> None:
        result = pack_evidence(
            [
                evidence("a", url="https://one.example/path", text="same"),
                evidence("b", url="https://two.example/path", text="same"),
            ],
            topic="same",
            budget=100,
            estimator=FixedEstimator(10),
        )
        self.assertEqual([item.id for item in result.selected], ["a", "b"])
        self.assertEqual(result.dropped, [])

    def test_budget_is_never_exceeded_and_reasons_are_complete(self) -> None:
        result = pack_evidence(
            [evidence("a"), evidence("b"), evidence("c")],
            topic="AI agent",
            budget=20,
            estimator=FixedEstimator(10),
        )
        self.assertEqual(result.token_total, 20)
        self.assertLessEqual(result.token_total, result.budget)
        self.assertEqual(len(result.dropped), 1)
        self.assertEqual(result.dropped[0].reason, "lower_rank")
        self.assertTrue(all(item.reason for item in result.dropped))

    def test_empty_evidence(self) -> None:
        result = pack_evidence([], topic="x", budget=10, estimator=FixedEstimator(1))
        self.assertEqual(result.selected, [])
        self.assertEqual(result.dropped, [])
        self.assertEqual(result.token_total, 0)

    def test_single_item_over_budget(self) -> None:
        result = pack_evidence(
            [evidence("large")],
            topic="x",
            budget=5,
            estimator=FixedEstimator(6),
        )
        self.assertEqual(result.selected, [])
        self.assertEqual(result.dropped[0].reason, "over_budget")

    def test_over_budget_is_only_used_when_item_exceeds_full_budget(self) -> None:
        result = pack_evidence(
            [evidence("a"), evidence("b"), evidence("large")],
            topic="AI agent",
            budget=10,
            estimator=FixedEstimator(6),
        )
        self.assertEqual(
            [item.reason for item in result.dropped],
            ["lower_rank", "lower_rank"],
        )

    def test_equal_scores_preserve_input_order(self) -> None:
        items = [
            evidence("z", text="AI agent z"),
            evidence("a", text="AI agent a"),
            evidence("m", text="AI agent m"),
        ]
        result = pack_evidence(
            items,
            topic="AI agent",
            budget=30,
            as_of=date(2026, 1, 2),
            estimator=FixedEstimator(10),
        )
        self.assertEqual([item.id for item in result.selected], ["z", "a", "m"])

    def test_context_event_exposes_all_drops(self) -> None:
        result = pack_evidence(
            [evidence("a"), evidence("b")],
            topic="AI",
            budget=10,
            estimator=FixedEstimator(10),
        )
        event = result.context_event(node="reporter")
        self.assertEqual(event["node"], "reporter")
        self.assertEqual(event["dropped_count"], 1)
        self.assertEqual(len(event["dropped"]), 1)

    def test_standard_library_estimator_and_defaults(self) -> None:
        estimator = HeuristicTokenEstimator()
        self.assertEqual(estimator.estimate("中文abcd"), 3)
        budget = ContextBudget()
        self.assertEqual(budget.reporter_tokens, 200_000)
        self.assertTrue(Settings(storage_path=Path("test.db")).context_packer_enabled)


if __name__ == "__main__":
    unittest.main()
