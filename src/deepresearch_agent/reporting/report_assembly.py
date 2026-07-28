from __future__ import annotations

import json

from deepresearch_agent.memory import prior_difference_rows
from deepresearch_agent.research_snapshot import ResearchSnapshot
from deepresearch_agent.schemas import ResearchState


def append_degradation_notice(report: str, state: ResearchState) -> str:
    events = state.metadata.get("degradation_events", [])
    lines = [report.rstrip()]
    if events:
        lines.extend(["", "## 数据获取降级"])
        for event in events:
            lines.append(
                "- "
                f"{event.get('tool', 'tool')} / {event.get('reason', 'unknown')}: "
                f"{event.get('impact', 'tool output unavailable')} "
                f"(attempts={int(event.get('attempts', 0))})"
            )
    critic = state.critic_report
    if critic and critic.forced_pass:
        lines.extend(["", "## 质量守卫强制放行"])
        lines.append(
            f"- Critic 在第 {state.critic_iteration} 轮后仍未通过；"
            "报告按迭代上限强制放行，未解决问题："
            + ", ".join(issue.issue_type for issue in critic.issues)
        )
    return "\n".join(lines)


def append_research_process(
    report: str,
    state: ResearchState,
    *,
    enabled: bool,
) -> str:
    if not enabled:
        return report
    process = state.metadata.get("research_process", [])
    if not process:
        return report
    lines = [report.rstrip(), "", "## 研究过程", ""]
    for item in process:
        iteration = int(item.get("iteration", 0))
        sufficiency = item.get("sufficiency", {})
        decision = item.get("decision", {})
        budget = item.get("budget", {})
        lines.extend(
            [
                f"### 第 {iteration} 轮",
                "",
                "- 检索意图："
                + json.dumps(item.get("queries", {}), ensure_ascii=False, sort_keys=True),
                "- 充分性总分：" f"{float(sufficiency.get('score', 0.0)):.3f}",
            ]
        )
        for metrics in sufficiency.get("by_sub_question", []):
            lines.append(
                "- "
                f"{metrics.get('sub_question_id')}: "
                f"evidence={metrics.get('evidence_count')}, "
                f"domains={metrics.get('independent_source_domains')}, "
                f"confidence={float(metrics.get('average_confidence', 0.0)):.3f}, "
                f"freshest_age_days={metrics.get('freshest_evidence_age_days')}, "
                f"critic_issues={metrics.get('unresolved_critic_issues')}, "
                f"missing_counterargument={metrics.get('missing_counterargument')}, "
                f"gaps={metrics.get('gaps', [])}"
            )
        lines.append(
            "- 循环决策："
            f"{decision.get('outcome')}；判据：{decision.get('criterion')}"
        )
        if budget:
            lines.append(
                "- 预算分配："
                + json.dumps(
                    {
                        "total_budget": budget.get("total_budget"),
                        "total_used": budget.get("total_used"),
                        "allocations": budget.get("allocations", {}),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        reflection_effect = item.get("reflection_effect")
        if isinstance(reflection_effect, dict):
            signals = reflection_effect.get("deterministic_signals", {})
            has_signal = isinstance(signals, dict) and any(
                bool(value) for value in signals.values()
            )
            if has_signal:
                lines.append(
                    "- 反思如何影响重规划：仅使用确定性跨轮信号 "
                    + json.dumps(signals, ensure_ascii=False, sort_keys=True)
                )
            else:
                lines.append(
                    "- 反思如何影响重规划：本轮未发现跨轮重复模式，因此没有追加反思定向条件。"
                )
            lines.append(
                "- 下一轮检索意图："
                + json.dumps(
                    reflection_effect.get("adjusted_queries", {}),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "；LLM 洞察未参与，待 019。"
            )
        if item.get("stop_boundary"):
            lines.append(f"- 停止说明：因 {item['stop_boundary']} 边界停止，覆盖可能不足。")
        lines.append("")
    return "\n".join(lines).rstrip()


def append_prior_differences(
    report: str,
    state: ResearchState,
    *,
    enabled: bool,
) -> str:
    if not enabled:
        return report
    prior_metadata = state.metadata.get("prior_memory", {})
    raw_snapshot = prior_metadata.get("snapshot") if isinstance(prior_metadata, dict) else None
    if not isinstance(raw_snapshot, dict):
        return report
    snapshot = ResearchSnapshot.model_validate(raw_snapshot)
    rows = prior_difference_rows(state, snapshot)
    state.metadata["prior_memory"]["differences"] = rows
    lines = [
        report.rstrip(),
        "",
        "## 与上期结论的差异",
        "",
        f"对比基准：{snapshot.as_of.isoformat()}；仅比较最近一期记忆。",
    ]
    for row in rows:
        evidence_ids = ", ".join(row["evidence_ids"]) or "无"
        lines.append(
            "- "
            f"{row['status']}：{row['prior']} {row['explanation']} "
            f"支撑 Evidence：{evidence_ids}"
        )
    return "\n".join(lines)
