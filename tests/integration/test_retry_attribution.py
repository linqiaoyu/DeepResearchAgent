from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from deepresearch_agent.schemas import ResearchState, RetryTask, Source
from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.workflow import DeepResearchEngine


class RetrySearchProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def search(self, query: str, top_k: int = 3, source_type: str | None = None) -> list[Source]:
        self.calls.append((query, source_type))
        key = query.replace(" ", "-")
        return [
            Source(
                id=f"source-{key}",
                title=f"Retry source for {query}",
                url=f"https://example.test/{key}",
                source_type=source_type or "official",
                published_at=date(2026, 2, 1),
                credibility=0.9,
                content=(
                    f"{query} has source-backed evidence with 42% measured improvement. "
                    "However compliance risk and operational constraints still require review."
                ),
            )
        ][:top_k]


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

    def test_multiple_retry_tasks_keep_distinct_sub_question_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db", max_critic_iter=1)
            store = SQLiteStore(settings.storage_path)
            provider = RetrySearchProvider()
            engine = DeepResearchEngine(settings=settings, store=store, search_tool=provider)
            plan = engine.planner.plan("AI Agent 在财富管理行业的落地机会研究", depth_level=2)
            first_subq = plan.sub_questions[0]
            second_subq = plan.sub_questions[1]
            state = ResearchState(topic=plan.topic, depth_level=2, plan=plan)
            state.retry_queue = [
                RetryTask(
                    reason="Targeted retry for first sub-question",
                    query="first retry evidence",
                    source_type="official",
                    sub_question_id=first_subq.id,
                ),
                RetryTask(
                    reason="Targeted retry for second sub-question",
                    query="second retry evidence",
                    source_type="industry_report",
                    sub_question_id=second_subq.id,
                ),
            ]

            engine._execute_retry_tasks(state)
            persisted = store.list_evidence(state.research_id)

        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(all(task.completed for task in state.retry_queue))
        self.assertGreater(len(state.evidence_store), 0)
        self.assertEqual({item.sub_question_id for item in state.evidence_store}, {first_subq.id, second_subq.id})
        self.assertEqual({item.sub_question_id for item in persisted}, {first_subq.id, second_subq.id})
        for item in state.evidence_store:
            if "first-retry-evidence" in item.source_url:
                self.assertEqual(item.sub_question_id, first_subq.id)
            elif "second-retry-evidence" in item.source_url:
                self.assertEqual(item.sub_question_id, second_subq.id)
            else:
                self.fail(f"Unexpected retry evidence URL: {item.source_url}")

    def test_retry_without_sub_question_id_falls_back_to_last_sub_question(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(storage_path=Path(tmp) / "research.db", max_critic_iter=1)
            store = SQLiteStore(settings.storage_path)
            provider = RetrySearchProvider()
            engine = DeepResearchEngine(settings=settings, store=store, search_tool=provider)
            plan = engine.planner.plan("AI Agent 在财富管理行业的落地机会研究", depth_level=2)
            fallback_subq = plan.sub_questions[-1]
            state = ResearchState(topic=plan.topic, depth_level=2, plan=plan)
            state.retry_queue = [
                RetryTask(
                    reason="Legacy retry without target sub-question",
                    query="legacy fallback evidence",
                    source_type="official",
                )
            ]

            engine._execute_retry_tasks(state)
            persisted = store.list_evidence(state.research_id)

        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(state.retry_queue[0].completed)
        self.assertGreater(len(state.evidence_store), 0)
        self.assertEqual({item.sub_question_id for item in state.evidence_store}, {fallback_subq.id})
        self.assertEqual({item.sub_question_id for item in persisted}, {fallback_subq.id})


if __name__ == "__main__":
    unittest.main()
