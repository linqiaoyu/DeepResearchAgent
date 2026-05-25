from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.evaluation import EvaluationHarness
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
            "avg_critic_catch_rate",
            "avg_answer_relevance",
            "avg_faithfulness",
            "avg_latency_seconds",
            "avg_cost_usd",
            "avg_token_used",
            "bad_case_categories",
        }
        numeric_aggregate_keys = expected_keys - {"bad_case_categories"}
        rate_metric_keys = {
            "avg_task_success_rate",
            "avg_citation_accuracy",
            "avg_critic_catch_rate",
            "avg_answer_relevance",
            "avg_faithfulness",
        }
        non_negative_metric_keys = {
            "avg_latency_seconds",
            "avg_cost_usd",
            "avg_token_used",
        }

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


if __name__ == "__main__":
    unittest.main()
