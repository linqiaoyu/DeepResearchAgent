from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.orchestration import RunScope, SearchQuota
from deepresearch_agent.schemas import ResearchState, RetryTask
from deepresearch_agent.settings import Settings
from deepresearch_agent.storage import SQLiteStore
from deepresearch_agent.tools import RunToolContext
from deepresearch_agent.workflow import DeepResearchEngine


class RetryBudgetSchedulingTests(unittest.TestCase):
    def test_retry_fanout_is_bounded_by_remaining_external_search_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._engine(Path(tmp))
            state = self._state_with_retries(3)
            context = RunToolContext.for_run(max_external_search_requests=4)
            context.consume_external_request("search", tool="tavily_search")
            context.consume_external_request("search", tool="tavily_search")
            scope = RunScope(context, SearchQuota(20))

            update = engine._retry_prepare_node(
                {"research_state": state.model_dump(mode="json")},
                run_scope=scope,
            )
            prepared = ResearchState.model_validate(update["research_state"])

        self.assertEqual(len(update["active_retry_task_ids"]), 1)
        self.assertEqual(sum(task.completed for task in prepared.retry_queue), 2)
        self.assertEqual(
            sum(
                record.query.startswith("[external_search_budget_deferred]")
                for record in prepared.search_records
            ),
            2,
        )
        event = prepared.metadata["retry_budget_scheduling_events"][-1]
        self.assertEqual(event["remaining_search_requests"], 2)
        self.assertEqual(event["search_request_bound_per_task"], 2)
        self.assertEqual(len(event["deferred_task_ids"]), 2)

    def test_exhausted_budget_routes_to_join_without_launching_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._engine(Path(tmp))
            state = self._state_with_retries(2)
            context = RunToolContext.for_run(max_external_search_requests=1)
            context.consume_external_request("search", tool="tavily_search")
            scope = RunScope(context, SearchQuota(20))
            graph_state = {"research_state": state.model_dump(mode="json")}
            graph_state.update(
                engine._retry_prepare_node(graph_state, run_scope=scope)
            )

            route = engine._send_retry_tasks(graph_state)
            prepared = ResearchState.model_validate(graph_state["research_state"])

        self.assertEqual(route, "retry_join")
        self.assertEqual(graph_state["active_retry_task_ids"], [])
        self.assertTrue(all(task.completed for task in prepared.retry_queue))

    @staticmethod
    def _engine(tmp: Path) -> DeepResearchEngine:
        settings = Settings(
            storage_path=tmp / "research.db",
            dynamic_capability_enabled=False,
        )
        return DeepResearchEngine(
            settings=settings,
            store=SQLiteStore(settings.storage_path),
        )

    @staticmethod
    def _state_with_retries(count: int) -> ResearchState:
        state = ResearchState(topic="retry budget")
        state.retry_queue = [
            RetryTask(
                id=f"retry-{index}",
                reason="missing evidence",
                query=f"query {index}",
                source_type="official",
            )
            for index in range(count)
        ]
        return state


if __name__ == "__main__":
    unittest.main()
