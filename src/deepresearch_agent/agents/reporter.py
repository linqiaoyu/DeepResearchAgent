from __future__ import annotations

from collections import defaultdict

from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.schemas import Evidence, ResearchState


class ReporterAgent:
    def report(self, state: ResearchState) -> str:
        if not state.plan:
            raise ValueError("Cannot report before planning.")
        evidence = state.evidence_store
        footnotes = build_footnote_maps(evidence)
        ref_map = footnotes.evidence_id_to_footnote
        lines: list[str] = [
            f"# {state.topic}",
            "",
            "## 摘要",
            self._summary(state, evidence, ref_map),
            "",
            "## 关键发现",
        ]
        for item in evidence[:6]:
            lines.append(f"- {item.claim} [^{ref_map[item.id]}]")

        by_subq: dict[str, list[Evidence]] = defaultdict(list)
        for item in evidence:
            by_subq[item.sub_question_id].append(item)

        lines.extend(["", "## 详细分析"])
        for sub_question in state.plan.sub_questions:
            lines.append(f"### {sub_question.question}")
            items = by_subq.get(sub_question.id, [])
            if not items:
                lines.append("当前没有足够证据，需要二次检索补齐。")
                continue
            for item in items[:3]:
                lines.append(f"- {item.claim} [^{ref_map[item.id]}]")

        lines.extend(["", "## 风险与限制"])
        if state.critic_report and state.critic_report.issues:
            for issue in state.critic_report.issues[:6]:
                affected = ", ".join(issue.affected_claims) or "n/a"
                lines.append(f"- {issue.issue_type} ({issue.severity}): {issue.message} Affected: {affected}.")
        else:
            lines.append("- Critic 未发现高优先级事实、引用或反方观点问题。")

        projections = [item for item in evidence if item.claim_type == "projection"]
        lines.extend(["", "## 未验证假设"])
        if projections:
            for item in projections[:4]:
                lines.append(f"- {item.claim} [^{ref_map[item.id]}]")
        else:
            lines.append("- 本轮报告未单独引入低置信度预测性结论。")

        lines.extend(["", "## 参考来源"])
        for item in footnotes.unique_refs:
            lines.append(
                f"[^{ref_map[item.id]}]: {item.source_title}. {item.source_url} "
                f"({item.source_pub_date.isoformat()})"
            )
        return "\n".join(lines)

    def _summary(self, state: ResearchState, evidence: list[Evidence], ref_map: dict[str, int]) -> str:
        if not evidence:
            return "本次研究尚未收集到足够证据。"
        first = evidence[0]
        quality = state.critic_report.overall_quality if state.critic_report else 0.0
        return (
            f"本报告围绕“{state.topic}”拆解为 {len(state.plan.sub_questions) if state.plan else 0} 个子问题，"
            f"累计抽取 {len(evidence)} 条证据。当前 Critic 质量分为 {quality:.2f}，"
            f"首要结论可追溯到来源 [^{ref_map[first.id]}]。"
        )
