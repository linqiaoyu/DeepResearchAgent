from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.workflow import DeepResearchEngine
from langgraph.types import Send


class LangGraphMigrationTests(unittest.TestCase):
    def test_researcher_routes_sub_questions_with_send_fanout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db")
            engine = DeepResearchEngine(settings=settings, store=SQLiteStore(settings.storage_path))
            plan = engine.planner.plan("AI Agent 在财富管理行业的落地机会研究", depth_level=2)
            state = ResearchState(topic=plan.topic, depth_level=2, plan=plan)
            graph_state = {"research_state": state.model_dump(mode="json")}

            graph_state.update(engine._research_prepare_node(graph_state))
            sends = engine._send_research_tasks(graph_state)

        self.assertIsInstance(sends, list)
        self.assertEqual(len(sends), len(plan.sub_questions))
        self.assertTrue(all(isinstance(item, Send) for item in sends))
        self.assertEqual({item.node for item in sends}, {"research_one"})
        self.assertEqual(
            {item.arg["fanout_sub_question"]["id"] for item in sends},
            {item.id for item in plan.sub_questions},
        )

    def test_critic_condition_routes_to_retry_until_force_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            retry_settings = Settings(storage_path=Path(tmp) / "retry.db", max_critic_iter=2)
            retry_engine = DeepResearchEngine(
                settings=retry_settings,
                store=SQLiteStore(retry_settings.storage_path),
            )
            plan = retry_engine.planner.plan("AI Agent 在财富管理行业的落地机会研究", depth_level=1)
            retry_state = ResearchState(topic=plan.topic, depth_level=1, plan=plan)
            retry_update = retry_engine._critic_node(
                {"research_state": retry_state.model_dump(mode="json")}
            )

            force_settings = Settings(storage_path=Path(tmp) / "force.db", max_critic_iter=1)
            force_engine = DeepResearchEngine(
                settings=force_settings,
                store=SQLiteStore(force_settings.storage_path),
            )
            force_state = ResearchState(topic=plan.topic, depth_level=1, plan=plan)
            force_update = force_engine._critic_node(
                {"research_state": force_state.model_dump(mode="json")}
            )
            forced = force_engine._state_from_graph_values(force_update)

        self.assertEqual(retry_engine._route_after_critic(retry_update), "retry_prepare")
        self.assertEqual(force_engine._route_after_critic(force_update), "reporter")
        self.assertIsNotNone(forced.critic_report)
        self.assertTrue(forced.critic_report.forced_pass)
        self.assertTrue(forced.critic_report.passed)

    def test_sqlite_saver_interrupt_resume_with_same_research_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db", max_critic_iter=1)
            engine = DeepResearchEngine(settings=settings, store=SQLiteStore(settings.storage_path))

            interrupted = engine.run(
                topic="AI Agent 在财富管理行业的落地机会研究",
                depth_level=1,
                interrupt_before=["extractor"],
            )
            checkpoint_before_resume = engine.graph.get_state(
                {"configurable": {"thread_id": interrupted.research_id}}
            )
            resumed = engine.run(research_id=interrupted.research_id, resume=True)

            with sqlite3.connect(settings.storage_path) as conn:
                checkpoint_rows = conn.execute(
                    "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?",
                    (interrupted.research_id,),
                ).fetchone()[0]

        self.assertEqual(interrupted.current_phase, "extracting")
        self.assertIn("extractor", checkpoint_before_resume.next)
        self.assertEqual(resumed.research_id, interrupted.research_id)
        self.assertEqual(resumed.status, "done")
        self.assertGreater(len(resumed.evidence_store), 0)
        self.assertGreater(checkpoint_rows, 0)


if __name__ == "__main__":
    unittest.main()
