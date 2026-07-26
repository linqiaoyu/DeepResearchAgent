from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


class WorkflowCompletionGuardTest(unittest.TestCase):
    def test_done_state_without_report_raises_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                storage_path=Path(temp_dir) / "research.db",
                runs_root=Path(temp_dir) / "runs",
                run_manifest_enabled=False,
                structured_logging_enabled=False,
            )
            engine = DeepResearchEngine(settings=settings)
            state = ResearchState(topic="guard", status="done", current_phase="done")
            engine.graph.invoke = Mock(return_value={"research_state": state.model_dump(mode="json")})

            with self.assertRaisesRegex(RuntimeError, "without final_report"):
                engine.run(topic="guard")

            checkpoint = engine.load_state(state.research_id)
            self.assertIsNone(checkpoint)
            engine._checkpoint_conn.close()


if __name__ == "__main__":
    unittest.main()
