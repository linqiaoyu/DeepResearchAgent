from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.workflow import DeepResearchEngine


class CheckpointTests(unittest.TestCase):
    def test_resume_preserves_evidence_and_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db", max_critic_iter=1)
            store = SQLiteStore(settings.storage_path)
            engine = DeepResearchEngine(settings=settings, store=store)
            paused = engine.run(
                topic="AI Agent 在财富管理行业的落地机会研究",
                depth_level=2,
                stop_after_phase="extracting",
            )
            evidence_count = len(paused.evidence_store)
            resumed = engine.run(research_id=paused.research_id, resume=True)

        self.assertEqual(paused.status, "paused")
        self.assertGreater(evidence_count, 0)
        self.assertEqual(resumed.status, "done")
        self.assertGreaterEqual(len(resumed.evidence_store), evidence_count)
        self.assertIsNotNone(resumed.final_report)


if __name__ == "__main__":
    unittest.main()

