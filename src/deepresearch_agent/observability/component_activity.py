from __future__ import annotations

from typing import Any, Literal

from deepresearch_agent.schemas import ResearchState


ComponentStatus = Literal["completed", "bypassed", "failed"]


def record_component_activity(
    state: ResearchState,
    *,
    component: str,
    enabled: bool,
    status: ComponentStatus,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
) -> None:
    """Append one observable component event without changing workflow content."""

    activity = state.metadata.setdefault("component_activity", {})
    summary = activity.setdefault(
        component,
        {
            "enabled": enabled,
            "invocations": 0,
            "completed": 0,
            "bypassed": 0,
            "failed": 0,
            "events": [],
        },
    )
    summary["enabled"] = enabled
    summary["invocations"] = int(summary["invocations"]) + 1
    summary[status] = int(summary[status]) + 1
    summary["events"].append(
        {
            "status": status,
            "inputs": dict(inputs or {}),
            "outputs": dict(outputs or {}),
        }
    )
