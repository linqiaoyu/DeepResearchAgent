from __future__ import annotations

import json

from deepresearch_agent.schemas import AgentDecision, ResearchState


def record_agent_decision(
    state: ResearchState,
    decision: AgentDecision,
) -> None:
    """Persist one decision in state and the structured run trace."""
    state.agent_decisions.append(decision)
    trace = state.metadata.setdefault("run_trace", {})
    trace.setdefault("agent_decisions", []).append(
        decision.model_dump(mode="json")
    )
    from deepresearch_agent.trajectory import active_trajectory_recorder

    recorder = active_trajectory_recorder()
    if recorder:
        recorder.record_decision(decision)


def canonical_decision_json(decision: AgentDecision) -> str:
    return json.dumps(
        decision.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def append_decision_record(
    report: str,
    decisions: list[AgentDecision],
) -> str:
    if not decisions:
        return report
    lines = [report, "", "## Agent 决策记录", ""]
    for decision in decisions:
        iteration = (
            f"；iteration={decision.iteration}"
            if decision.iteration is not None
            else ""
        )
        lines.append(
            f"- `{decision.decision_type}` by `{decision.made_by}`"
            f"{iteration}：{decision.outcome}。判据：{decision.criterion}"
        )
        lines.append(
            "  - 依据："
            + json.dumps(
                decision.inputs,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        lines.append(
            "  - 已考虑替代项："
            + (
                "、".join(decision.alternatives_considered)
                if decision.alternatives_considered
                else "无"
            )
        )
    return "\n".join(lines)
