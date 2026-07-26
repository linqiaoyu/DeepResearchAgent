from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.settings import Settings
from deepresearch_agent.tools.fixture_search import FixtureSearchTool
from deepresearch_agent.workflow import DeepResearchEngine


class AgentAblationTests(unittest.TestCase):
    def test_critic_disabled_is_bypassed_and_observable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                runs_root=Path(tmp) / "runs",
                critic_enabled=False,
                max_critic_iter=1,
                structured_logging_enabled=False,
            )
            engine = DeepResearchEngine(
                settings=settings,
                search_tool=FixtureSearchTool(),
            )
            try:
                state = engine.run(
                    topic="AI Agent 在财富管理行业的落地机会研究",
                    depth_level=1,
                )
            finally:
                engine._checkpoint_conn.close()

        self.assertIsNone(state.critic_report)
        activity = state.metadata["component_activity"]["critic"]
        self.assertFalse(activity["enabled"])
        self.assertEqual(activity["bypassed"], 1)
        self.assertEqual(activity["completed"], 0)
        self.assertIn("Critic 未执行", state.final_report or "")

    def test_extractor_disabled_preserves_researcher_evidence_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                runs_root=Path(tmp) / "runs",
                extractor_enabled=False,
                critic_enabled=False,
                structured_logging_enabled=False,
            )
            engine = DeepResearchEngine(
                settings=settings,
                search_tool=FixtureSearchTool(),
            )
            try:
                state = engine.run(
                    topic="AI Agent 在财富管理行业的落地机会研究",
                    depth_level=1,
                )
            finally:
                engine._checkpoint_conn.close()

        activity = state.metadata["component_activity"]["extractor"]
        self.assertFalse(activity["enabled"])
        self.assertEqual(activity["bypassed"], 1)
        self.assertTrue(
            all(item.source_kind == "structured" for item in state.evidence_store)
        )

    def test_disabled_memories_record_bypass_without_read_or_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                storage_path=Path(tmp) / "research.db",
                runs_root=Path(tmp) / "runs",
                prior_memory_enabled=False,
                procedural_memory_enabled=False,
                context_packer_enabled=False,
                structured_logging_enabled=False,
            )
            engine = DeepResearchEngine(
                settings=settings,
                search_tool=FixtureSearchTool(),
            )
            try:
                state = engine.run(
                    topic="AI Agent 在财富管理行业的落地机会研究",
                    depth_level=1,
                )
            finally:
                engine._checkpoint_conn.close()

        activity = state.metadata["component_activity"]
        self.assertEqual(activity["episodic_memory"]["bypassed"], 1)
        self.assertEqual(activity["procedural_memory_read"]["bypassed"], 1)
        self.assertEqual(activity["working_memory"]["bypassed"], 1)
        self.assertNotIn("procedural_memory_write", activity)


if __name__ == "__main__":
    unittest.main()
