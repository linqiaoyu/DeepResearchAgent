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

        self.assertEqual(summary["cases"], 2)
        self.assertIn("avg_citation_accuracy", summary)
        self.assertIn("avg_critic_catch_rate", summary)
        self.assertIn("avg_cost_usd", summary)
        self.assertIn("avg_token_used", summary)
        self.assertIn("bad_case_categories", summary)
        self.assertIsInstance(summary["bad_case_categories"], dict)


if __name__ == "__main__":
    unittest.main()
