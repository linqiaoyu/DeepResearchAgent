from __future__ import annotations

from typing import Any, Literal

from deepresearch_agent.schemas import ResearchState


#: R111: `composed` is not `completed`. Nine capabilities are decided when
#: the run is assembled -- the tool contract wrapper, the structured logger,
#: fail-fast validation, the injection guard, both rerank settings -- and
#: have no unit of work to count. Recording them as `completed` would claim
#: they did something; leaving them unrecorded is what made 9 of 25 declared
#: capabilities unprovable from a run. `composed` says exactly what is known:
#: this capability was wired into this run.
ComponentStatus = Literal["completed", "bypassed", "failed", "composed"]


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
            "composed": 0,
            "events": [],
        },
    )
    summary.setdefault("composed", 0)
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
