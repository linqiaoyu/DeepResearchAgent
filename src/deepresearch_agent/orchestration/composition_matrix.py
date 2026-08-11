from __future__ import annotations

from dataclasses import dataclass

from deepresearch_agent.observability import record_component_activity
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.trajectory import (
    NodeTransitionTrace,
    TrajectoryRecorder,
    verify_trajectory_offline,
)


PAIRWISE_TECHNOLOGIES: tuple[str, ...] = (
    "planning",
    "tool_calling",
    "rag",
    "mcp",
    "skills",
    "memory",
    "reflection",
)


@dataclass(frozen=True)
class CombinationRun:
    row_id: int
    enabled: frozenset[str]
    active: frozenset[str]
    budget_used: int
    budget_conflicts: int
    trajectory_conflicts: int
    state_conflicts: int


def pairwise_rows() -> tuple[frozenset[str], ...]:
    """Eight rows cover all four binary states for every pair of 7 factors."""

    rows: list[frozenset[str]] = []
    for row in range(8):
        enabled = {
            technology
            for vector, technology in enumerate(PAIRWISE_TECHNOLOGIES, start=1)
            if (row & vector).bit_count() % 2 == 1
        }
        rows.append(frozenset(enabled))
    return tuple(rows)


def execute_pairwise_matrix() -> tuple[CombinationRun, ...]:
    """Exercise shared state, budget, activity, and trajectory ownership."""

    results: list[CombinationRun] = []
    for row_id, enabled in enumerate(pairwise_rows()):
        state = ResearchState(topic=f"pairwise-combination-{row_id}")
        recorder = TrajectoryRecorder(
            run_id=f"pairwise-{row_id}",
            request={
                "topic": state.topic,
                "mode": "deterministic",
                "depth_level": 1,
                "recorded_plan": {},
                "combination": sorted(enabled),
            },
        )
        budget_limit = len(PAIRWISE_TECHNOLOGIES)
        budget_used = 0
        state_conflicts = 0
        for technology in PAIRWISE_TECHNOLOGIES:
            is_active = technology in enabled
            record_component_activity(
                state,
                component=f"pairwise_{technology}",
                enabled=is_active,
                status="completed" if is_active else "bypassed",
                inputs={"row_id": row_id},
            )
            if not is_active:
                continue
            key = f"pairwise:{technology}"
            if key in state.metadata:
                state_conflicts += 1
            state.metadata[key] = {"status": "active", "budget_units": 1}
            budget_used += 1
            recorder.record_node_transition(
                NodeTransitionTrace(
                    node=f"pairwise_{technology}",
                    input_summary={"row_id": row_id},
                    output_summary={"state_key": key, "budget_units": 1},
                )
            )
        recorder.finalize(
            manifest_ref=None,
            artifacts={"report.md": "\n".join(sorted(enabled))},
        )
        trajectory_conflicts = 0
        try:
            verification = verify_trajectory_offline(recorder.trajectory)
            if not verification.trace_commitment_verified:
                trajectory_conflicts += 1
        except ValueError:
            trajectory_conflicts += 1
        activity = state.metadata.get("component_activity", {})
        if len(activity) != len(PAIRWISE_TECHNOLOGIES):
            state_conflicts += 1
        results.append(
            CombinationRun(
                row_id=row_id,
                enabled=enabled,
                active=frozenset(
                    technology
                    for technology in PAIRWISE_TECHNOLOGIES
                    if activity.get(f"pairwise_{technology}", {}).get("completed")
                ),
                budget_used=budget_used,
                budget_conflicts=int(budget_used > budget_limit),
                trajectory_conflicts=trajectory_conflicts,
                state_conflicts=state_conflicts,
            )
        )
    return tuple(results)
