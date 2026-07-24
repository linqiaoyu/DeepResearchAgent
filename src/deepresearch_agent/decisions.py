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


def append_decision_chain(
    report: str,
    decisions: list[AgentDecision],
) -> str:
    """Explain cross-decision dependencies using the existing decision log."""

    woven = [
        item
        for item in decisions
        if "decision_context_fields" in item.inputs
        or item.decision_type
        in {"numeric_consistency_check", "capability_selection"}
    ]
    if not woven:
        return report
    lines = [report, "", "## 决策链", ""]
    for decision in woven:
        context = decision.inputs.get("decision_context", {})
        if not isinstance(context, dict):
            context = {}
        if decision.decision_type.startswith("branch_budget_"):
            budget = context.get("budget", {})
            prior = context.get("prior_classifications", [])
            verify_ids = [
                str(item.get("sub_question_id"))
                for item in prior
                if isinstance(item, dict) and item.get("kind") == "verify"
            ]
            lines.append(
                "- 预算分配读取了充分性与跨期优先级："
                f"余额 {_budget_remaining(budget)}；"
                f"verify 子问题 {verify_ids or '无'}；"
                f"因此 `{decision.outcome}`。"
            )
        elif decision.decision_type == "bounded_loop_control":
            budget = context.get("budget", {})
            sufficiency = context.get("sufficiency", [])
            weak = [
                str(item.get("sub_question_id"))
                for item in sufficiency
                if isinstance(item, dict) and not item.get("sufficient", False)
            ]
            lines.append(
                "- 循环同时权衡预算与研究充分性："
                f"余额 {_budget_remaining(budget)}，"
                f"仍有缺口的子问题 {weak or '无'}；"
                f"因此 `{decision.outcome}`。"
            )
        elif decision.decision_type == "research_replan":
            issues = context.get("unresolved_critic_issues", [])
            issue_types = [
                str(item.get("issue_type"))
                for item in issues
                if isinstance(item, dict)
            ]
            lines.append(
                "- 重规划承接 Critic 未解决问题："
                f"问题类型 {issue_types or '无'}；"
                f"下一轮结果为 `{decision.outcome}`。"
            )
        elif decision.decision_type == "prior_memory_classification":
            lines.append(
                "- 跨期分类读取当前轮次、预算与 Critic 状态后，"
                f"将子问题判为 `{decision.outcome}`。"
            )
        elif decision.decision_type == "numeric_consistency_check":
            lines.append(
                "- 数值校验把算术结论反馈给 Critic 与后续重规划："
                f"`{decision.outcome}`。"
            )
        elif decision.decision_type == "capability_selection":
            lines.append(
                "- 能力选择结合子问题类型与候选集："
                f"`{decision.outcome}`。"
            )
    lines.extend(
        [
            "",
            "这条链说明后续决策读取了上游决策形成的同一只读上下文，"
            "而不是彼此独立地按固定顺序执行。",
        ]
    )
    return "\n".join(lines)


def _budget_remaining(value: object) -> str:
    if not isinstance(value, dict):
        return "未记录"
    remaining = value.get("remaining", "未记录")
    total = value.get("total", "未记录")
    return f"{remaining}/{total}"
