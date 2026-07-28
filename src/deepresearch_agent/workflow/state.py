"""The reducer-aware state schema shared by workflow graph assembly."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _merge_dicts(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(left or {})
    merged.update(right or {})
    return merged


class ResearchGraphState(TypedDict, total=False):
    research_state: dict[str, Any]
    started_at: float
    stop_after_phase: str | None
    active_sub_question_ids: list[str]
    active_retry_task_ids: list[str]
    fanout_sub_question: dict[str, Any]
    fanout_retry_task: dict[str, Any]
    research_sources: Annotated[dict[str, list[dict[str, Any]]], _merge_dicts]
    research_records: Annotated[dict[str, list[dict[str, Any]]], _merge_dicts]
    research_structured_evidence: Annotated[
        dict[str, list[dict[str, Any]]], _merge_dicts
    ]
    research_structured_stats: Annotated[dict[str, dict[str, int]], _merge_dicts]
    research_symbol_resolutions: Annotated[
        dict[str, list[dict[str, Any]]], _merge_dicts
    ]
    research_decisions: Annotated[dict[str, list[dict[str, Any]]], _merge_dicts]
    research_budget_usage: Annotated[dict[str, int], _merge_dicts]
    research_branch_coverage: Annotated[dict[str, dict[str, Any]], _merge_dicts]
    retry_sources: Annotated[dict[str, list[dict[str, Any]]], _merge_dicts]
    retry_records: Annotated[dict[str, dict[str, Any]], _merge_dicts]
