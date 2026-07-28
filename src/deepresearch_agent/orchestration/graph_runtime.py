"""Framework-neutral runtime wrappers for workflow graph nodes."""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable, Mapping
from typing import Any, Protocol
from urllib.parse import urlsplit

from deepresearch_agent.orchestration.contracts import (
    NodeContract,
    RunScope,
    enforce_node_contract,
)
from deepresearch_agent.trajectory import (
    NodeTransitionTrace,
    active_trajectory_recorder,
)


class EventLogger(Protocol):
    """The structured logging boundary required by graph runtime wrappers."""

    def event(self, event: str, **fields: Any) -> None: ...


_SCOPED_NODE_NAMES = frozenset(
    {
        "research_prepare",
        "research_one",
        "research_join",
        "research_loop_decide",
        "research_refine",
        "retry_one",
        "reporter",
    }
)


def trace_graph_summary(value: Any) -> dict[str, Any]:
    """Return stable, non-content summaries for graph lifecycle events."""

    if not isinstance(value, Mapping):
        return {"type": type(value).__name__}
    raw_state = value.get("research_state", {})
    if hasattr(raw_state, "model_dump"):
        raw_state = raw_state.model_dump(mode="json")
    if not isinstance(raw_state, Mapping):
        raw_state = {}
    summary: dict[str, Any] = {
        "phase": raw_state.get("current_phase"),
        "status": raw_state.get("status"),
        "source_count": len(raw_state.get("sources", [])),
        "evidence_count": len(raw_state.get("evidence_store", [])),
        "retry_count": len(raw_state.get("retry_queue", [])),
    }
    evidence_domains = sorted(
        {
            urlsplit(str(item.get("source_url", ""))).netloc.lower()
            for item in raw_state.get("evidence_store", [])
            if isinstance(item, Mapping) and item.get("source_url")
        }
    )
    if evidence_domains:
        summary["evidence_source_domains"] = evidence_domains
    critic_report = raw_state.get("critic_report")
    if isinstance(critic_report, Mapping):
        issue_types = sorted(
            str(item.get("issue_type"))
            for item in critic_report.get("issues", [])
            if isinstance(item, Mapping) and item.get("issue_type")
        )
        if issue_types:
            summary["critic_issue_types"] = issue_types
    sub_question = value.get("fanout_sub_question")
    if isinstance(sub_question, Mapping):
        summary["sub_question_id"] = sub_question.get("id")
    retry_task = value.get("fanout_retry_task")
    if isinstance(retry_task, Mapping):
        summary["retry_task_id"] = retry_task.get("id")
    return summary


class GraphRuntime:
    """Apply contracts, run scope injection, and trace events to graph nodes."""

    def __init__(
        self,
        node_contracts: Mapping[str, NodeContract],
        logger: EventLogger,
    ) -> None:
        self._node_contracts = node_contracts
        self._logger = logger

    def wrap_node(self, name: str, node: Callable[..., Mapping[str, Any]]):
        """Return the LangGraph-compatible wrapper for one workflow node."""

        def runtime_node(graph_state: Mapping[str, Any], runtime: Any):
            if not isinstance(runtime.context, RunScope):
                raise AssertionError("LangGraph runtime context is not a RunScope")
            if name in _SCOPED_NODE_NAMES:
                return node(graph_state, run_scope=runtime.context)
            return node(graph_state)

        contracted = enforce_node_contract(self._node_contracts[name], runtime_node)

        def traced(graph_state: Mapping[str, Any], runtime: Any):
            started = time.perf_counter()
            self._logger.event(
                "node_started",
                node=name,
                input_summary=trace_graph_summary(graph_state),
            )
            try:
                result = contracted(graph_state, runtime)
            except Exception as exc:
                self._logger.event(
                    "node_failed",
                    node=name,
                    input_summary=trace_graph_summary(graph_state),
                    elapsed_seconds=round(time.perf_counter() - started, 6),
                    error_type=type(exc).__name__,
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )
                recorder = active_trajectory_recorder()
                if recorder:
                    recorder.record_node_transition(
                        NodeTransitionTrace(
                            node=name,
                            input_summary=trace_graph_summary(graph_state),
                            output_summary={
                                "status": "failed",
                                "error_type": type(exc).__name__,
                            },
                            status="failed",
                            error_type=type(exc).__name__,
                            error_message=str(exc) or type(exc).__name__,
                        )
                    )
                raise
            self._logger.event(
                "node_finished",
                node=name,
                output_summary=trace_graph_summary(result),
                elapsed_seconds=round(time.perf_counter() - started, 6),
            )
            recorder = active_trajectory_recorder()
            if recorder:
                recorder.record_node_transition(
                    NodeTransitionTrace(
                        node=name,
                        input_summary=trace_graph_summary(graph_state),
                        output_summary=trace_graph_summary(result),
                    )
                )
            return result

        return traced
