"""Retry fan-out nodes for the workflow engine."""

from __future__ import annotations

from typing import Any

from deepresearch_agent.orchestration import RunScope
from deepresearch_agent.schemas import RetryTask, SearchRecord, Source, utc_now
from langgraph.types import Send

ResearchGraphState = dict[str, Any]


class RetryNodes:
    """Node methods that fan out, execute, and join retry tasks."""

    _RETRY_SEARCH_REQUEST_BOUND = 2

    def _retry_prepare_node(
        self,
        graph_state: ResearchGraphState,
        *,
        run_scope: RunScope,
    ) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        pending = [task for task in state.retry_queue if not task.completed]
        budget = run_scope.tool_context.external_request_budget
        if budget is None:
            active = pending
            deferred: list[RetryTask] = []
            remaining: int | None = None
        else:
            snapshot = budget.snapshot()
            remaining = max(
                0,
                int(snapshot["max_search_requests"])
                - int(snapshot["search_requests"]),
            )
            capacity = remaining // self._RETRY_SEARCH_REQUEST_BOUND
            active = pending[:capacity]
            deferred = pending[capacity:]

        if deferred:
            for task in deferred:
                task.completed = True
                state.search_records.append(
                    SearchRecord(
                        query=f"[external_search_budget_deferred] {task.query}",
                        source_ids=[],
                    )
                )
            state.metadata.setdefault("retry_budget_scheduling_events", []).append(
                {
                    "candidate_task_ids": [task.id for task in pending],
                    "scheduled_task_ids": [task.id for task in active],
                    "deferred_task_ids": [task.id for task in deferred],
                    "remaining_search_requests": remaining,
                    "search_request_bound_per_task": (
                        self._RETRY_SEARCH_REQUEST_BOUND
                    ),
                    "reason": "insufficient_run_search_budget",
                }
            )
        return {
            "research_state": self._dump_state(state),
            "active_retry_task_ids": [task.id for task in active],
        }

    def _send_retry_tasks(self, graph_state: ResearchGraphState) -> list[Send] | str:
        state = self._state_from_graph_values(graph_state)
        active_ids = set(graph_state.get("active_retry_task_ids", []))
        sends = [
            Send(
                "retry_one",
                {
                    "research_state": graph_state["research_state"],
                    "fanout_retry_task": task.model_dump(mode="json"),
                },
            )
            for task in state.retry_queue
            if task.id in active_ids
        ]
        return sends or "retry_join"

    def _retry_one_node(
        self, graph_state: ResearchGraphState, *, run_scope: RunScope
    ) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        task = RetryTask.model_validate(graph_state["fanout_retry_task"])
        if (
            self.settings.dynamic_capability_enabled
            and task.sub_question_id
        ):
            selections = state.metadata.get(
                "capability_selections",
                {},
            )
            selection = (
                selections.get(task.sub_question_id, {})
                if isinstance(selections, dict)
                else {}
            )
            selected = (
                selection.get("selected_capabilities", [])
                if isinstance(selection, dict)
                else []
            )
            if "web_search" not in selected:
                return {
                    "retry_sources": {task.id: []},
                    "retry_records": {
                        task.id: SearchRecord(
                            query=(
                                "[capability_not_selected] "
                                f"{task.query}"
                            ),
                            source_ids=[],
                        ).model_dump(mode="json")
                    },
                }
        sources, record = self.researcher.retry(task.query, task.source_type, run_scope=run_scope)
        return {
            "retry_sources": {task.id: [source.model_dump(mode="json") for source in sources]},
            "retry_records": {task.id: record.model_dump(mode="json")},
        }

    def _retry_join_node(self, graph_state: ResearchGraphState) -> ResearchGraphState:
        state = self._state_from_graph_values(graph_state)
        if not state.plan:
            return self._state_output(state)
        source_by_url: dict[str, Source] = {source.url: source for source in state.sources}
        evidence_by_id = {item.id: item for item in state.evidence_store}
        active_ids = set(graph_state.get("active_retry_task_ids", []))
        source_batches = graph_state.get("retry_sources", {})
        record_batches = graph_state.get("retry_records", {})

        for task in state.retry_queue:
            if task.id not in active_ids:
                continue
            target_subq = self._retry_target_subquestion(state, task.sub_question_id)
            sources = [Source.model_validate(item) for item in source_batches.get(task.id, [])]
            record_data = record_batches.get(task.id)
            if record_data:
                state.search_records.append(SearchRecord.model_validate(record_data))
            for source in sources:
                source_by_url[source.url] = source
            extracted = self.extractor.extract(state.research_id, target_subq, sources)
            if self.settings.execution_mode == "llm":
                state.metadata.setdefault("llm_stats", {}).setdefault("extractor", []).append(
                    {"sub_question_id": target_subq.id, "retry_task_id": task.id, **self.extractor.last_stats}
                )
            for item in extracted:
                evidence_by_id[item.id] = item
            task.completed = True

        state.sources = list(source_by_url.values())
        state.evidence_store = self._sorted_evidence(list(evidence_by_id.values()))
        self.store.add_evidence_many(state.evidence_store)
        state.current_phase = "critiquing"
        state.status = "running"
        state.updated_at = utc_now()
        return self._state_output(state)
