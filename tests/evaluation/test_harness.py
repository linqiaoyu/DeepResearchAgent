from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.evaluation import (
    EvaluationHarness,
    compare_metric_summaries,
    format_metric_comparison,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.workflow import DeepResearchEngine


class HarnessTests(unittest.TestCase):
    def test_harness_returns_aggregate_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db", max_critic_iter=1)
            engine = DeepResearchEngine(settings=settings, store=SQLiteStore(settings.storage_path))
            summary = EvaluationHarness(engine=engine).run(limit=2)

        expected_keys = {
            "cases",
            "avg_task_success_rate",
            "avg_citation_accuracy",
            "avg_citation_resolution_rate",
            "avg_critic_catch_rate",
            "avg_lexical_overlap",
            "avg_semantic_relevance",
            "avg_citation_density",
            "avg_semantic_faithfulness",
            "avg_latency_seconds",
            "avg_cost_usd",
            "avg_token_used",
            "bad_case_categories",
        }
        numeric_aggregate_keys = expected_keys - {
            "bad_case_categories",
            "avg_cost_usd",
            "avg_token_used",
            "avg_semantic_relevance",
            "avg_semantic_faithfulness",
        }
        rate_metric_keys = {
            "avg_task_success_rate",
            "avg_citation_accuracy",
            "avg_citation_resolution_rate",
            "avg_critic_catch_rate",
            "avg_lexical_overlap",
            "avg_citation_density",
        }
        non_negative_metric_keys = {"avg_latency_seconds"}

        self.assertTrue(expected_keys.issubset(summary.keys()))
        self.assertIsInstance(summary["cases"], int)
        self.assertEqual(summary["cases"], 2)
        self.assertGreater(summary["cases"], 0)
        self.assertIsInstance(summary["bad_case_categories"], dict)
        for key in numeric_aggregate_keys:
            with self.subTest(key=key):
                self.assertIsInstance(summary[key], (int, float))
        for key in rate_metric_keys:
            with self.subTest(key=key):
                self.assertGreaterEqual(summary[key], 0.0)
                self.assertLessEqual(summary[key], 1.0)
        for key in non_negative_metric_keys:
            with self.subTest(key=key):
                self.assertGreaterEqual(summary[key], 0.0)
        # Fixture runs have no provider ledger.  The harness must make that
        # absence explicit rather than emitting synthetic cost/token figures.
        self.assertIsNone(summary["avg_cost_usd"])
        self.assertIsNone(summary["avg_token_used"])

    def test_metric_diff_allows_latency_fluctuation(self) -> None:
        baseline = {
            "avg_citation_accuracy": 1.0,
            "avg_citation_resolution_rate": 1.0,
            "avg_citation_density": 0.9,
            "avg_critic_catch_rate": 0.8,
            "avg_cost_usd": 0.02,
            "avg_latency_seconds": 0.01,
            "avg_token_used": 1000,
            "bad_case_categories": {"numeric_conflict": 2},
        }
        current = {
            **baseline,
            "avg_latency_seconds": 1.5,
        }

        comparison = compare_metric_summaries(current=current, baseline=baseline)

        self.assertEqual(comparison["status"], "pass")
        self.assertEqual(comparison["metrics"]["avg_latency_seconds"]["status"], "pass")
        self.assertFalse(comparison["metrics"]["avg_latency_seconds"]["gated"])
        self.assertIn("avg_latency_seconds", format_metric_comparison(comparison))

    def test_metric_diff_fails_quality_drop_and_bad_case_increase(self) -> None:
        baseline = {
            "avg_citation_accuracy": 1.0,
            "avg_citation_resolution_rate": 1.0,
            "avg_citation_density": 0.9,
            "avg_critic_catch_rate": 0.8,
            "avg_cost_usd": 0.02,
            "avg_latency_seconds": 0.01,
            "avg_token_used": 1000,
            "bad_case_categories": {"numeric_conflict": 2},
        }
        current = {
            **baseline,
            "avg_citation_accuracy": 0.95,
            "bad_case_categories": {"numeric_conflict": 3},
        }

        comparison = compare_metric_summaries(current=current, baseline=baseline)

        self.assertEqual(comparison["status"], "fail")
        self.assertEqual(comparison["metrics"]["avg_citation_accuracy"]["status"], "fail")
        self.assertEqual(comparison["bad_case_status"], "fail")
        self.assertIn("avg_citation_accuracy dropped", comparison["failures"][0])

    def test_metric_diff_fails_closed_when_a_gated_metric_is_unmeasured(self) -> None:
        baseline = {
            "avg_citation_accuracy": 1.0,
            "avg_citation_resolution_rate": 1.0,
            "avg_citation_density": None,
            "avg_critic_catch_rate": 0.8,
        }
        comparison = compare_metric_summaries(current=baseline, baseline=baseline)

        citation_density = comparison["metrics"]["avg_citation_density"]
        self.assertEqual(comparison["status"], "fail")
        self.assertEqual(citation_density["status"], "unavailable")
        self.assertIsNone(citation_density["delta"])
        rendered = format_metric_comparison(comparison)
        self.assertIn("baseline=unavailable current=unavailable", rendered)
        self.assertTrue(
            any("avg_citation_density unavailable" in item for item in comparison["failures"])
        )


if __name__ == "__main__":
    unittest.main()
