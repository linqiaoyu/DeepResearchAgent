from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.workflow import DeepResearchEngine


class WorkflowTests(unittest.TestCase):
    def test_full_workflow_generates_report_evidence_and_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db", max_critic_iter=2)
            engine = DeepResearchEngine(settings=settings, store=SQLiteStore(settings.storage_path))
            state = engine.run(topic="AI Agent 在财富管理行业的落地机会研究", depth_level=2)

        self.assertEqual(state.status, "done")
        self.assertEqual(state.current_phase, "done")
        self.assertGreaterEqual(len(state.evidence_store), 4)
        self.assertIsNotNone(state.critic_report)
        self.assertIsNotNone(state.evaluation)
        self.assertIn("[^1]", state.final_report or "")
        self.assertGreaterEqual(state.evaluation.citation_accuracy, 0.9)


if __name__ == "__main__":
    unittest.main()

