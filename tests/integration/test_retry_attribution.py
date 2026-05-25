from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.schemas import ResearchState, RetryTask
from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.workflow import DeepResearchEngine


class RetryAttributionTests(unittest.TestCase):
    def test_retry_evidence_uses_task_sub_question_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db", max_critic_iter=1)
            engine = DeepResearchEngine(settings=settings, store=SQLiteStore(settings.storage_path))
            plan = engine.planner.plan("AI Agent 在财富管理行业的落地机会研究", depth_level=2)
            target_subq = plan.sub_questions[0]
            fallback_subq = plan.sub_questions[-1]
            state = ResearchState(topic=plan.topic, depth_level=2, plan=plan)
            state.retry_queue = [
                RetryTask(
                    reason="Targeted retry for market pain",
                    query="industry report pain points",
                    source_type="industry_report",
                    sub_question_id=target_subq.id,
                )
            ]

            engine._execute_retry_tasks(state)

        self.assertNotEqual(target_subq.id, fallback_subq.id)
        self.assertTrue(state.retry_queue[0].completed)
        self.assertGreater(len(state.evidence_store), 0)
        self.assertEqual({item.sub_question_id for item in state.evidence_store}, {target_subq.id})


if __name__ == "__main__":
    unittest.main()
