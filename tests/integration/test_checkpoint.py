from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.cli import run_checkpoint_demo
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

    def test_checkpoint_demo_script_output_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage_path = Path(tmp) / "checkpoint_demo.db"
            report_path = Path(tmp) / "report.md"
            old_argv = sys.argv
            buffer = io.StringIO()
            sys.argv = [
                "run_checkpoint_demo.py",
                "--storage",
                str(storage_path),
                "--output",
                str(report_path),
            ]
            try:
                with contextlib.redirect_stdout(buffer):
                    run_checkpoint_demo()
            finally:
                sys.argv = old_argv

            output = buffer.getvalue()

            self.assertIn("paused_phase=critiquing paused_status=paused", output)
            self.assertIn("resumed_phase=done resumed_status=done", output)
            self.assertIn(f"checkpoint_db={storage_path}", output)
            self.assertIn(f"report={report_path}", output)
            self.assertTrue(report_path.exists())
            self.assertGreater(report_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
