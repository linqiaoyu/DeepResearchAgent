from __future__ import annotations

import json
from collections import defaultdict

from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.llm import LLMClient, LLMClientError, StructuredOutputError
from deepresearch_agent.schemas import Evidence, ReportClaim, ReportDraft, ResearchState
from deepresearch_agent.settings import project_root


class ReporterAgent:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client
        self.last_stats: dict[str, int | bool | str] = {}

    def report(self, state: ResearchState) -> str:
        if not state.plan:
            raise ValueError("Cannot report before planning.")
        if self.llm_client:
            try:
                return self._llm_report(state)
            except (LLMClientError, StructuredOutputError, ValueError) as exc:
                self.last_stats = {"fallback": True, "error_type": type(exc).__name__}
        return self._deterministic_report(state)

    def _deterministic_report(self, state: ResearchState) -> str:
        evidence = state.evidence_store
        footnotes = build_footnote_maps(evidence)
        ref_map = footnotes.evidence_id_to_footnote
        lines: list[str] = [
            f"# {state.topic}",
            "",
            f"数据截至：{self._data_as_of(evidence)}",
            "",
            "免责声明：本报告为研究性输出，不构成投资建议。",
            "",
            "## 摘要",
            self._summary(state, evidence, ref_map),
            "",
            "## 关键发现",
        ]
        for item in evidence[:6]:
            lines.append(f"- {self._evidence_claim_text(item)} [^{ref_map[item.id]}]")

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
                lines.append(f"- {self._evidence_claim_text(item)} [^{ref_map[item.id]}]")

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

    def _llm_report(self, state: ResearchState) -> str:
        assert self.llm_client is not None
        prompt = (project_root() / "prompts" / "reporter.md").read_text(encoding="utf-8")
        evidence = state.evidence_store
        result = self.llm_client.complete(
            role="reporter",
            run_id=state.research_id,
            schema=ReportDraft,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "topic": state.topic,
                            "plan": state.plan.model_dump(mode="json") if state.plan else None,
                            "evidence": [
                                {
                                    "id": item.id,
                                    "sub_question_id": item.sub_question_id,
                                    "claim": item.claim,
                                    "claim_type": item.claim_type,
                                    "source_url": item.source_url,
                                    "source_title": item.source_title,
                                    "source_pub_date": item.source_pub_date.isoformat(),
                                    "extract_text": item.extract_text,
                                    "numeric_fields": item.numeric_fields.model_dump(mode="json")
                                    if item.numeric_fields
                                    else None,
                                }
                                for item in evidence
                            ],
                            "critic_report": state.critic_report.model_dump(mode="json")
                            if state.critic_report
                            else None,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        if not isinstance(result.parsed, ReportDraft):
            raise ValueError("Reporter did not return ReportDraft.")
        report, invalid_reference_count = self._render_llm_report(state, result.parsed)
        self.last_stats = {
            "fallback": False,
            "invalid_references": invalid_reference_count,
            "repair_attempts": result.repair_attempts,
        }
        return report

    def _render_llm_report(self, state: ResearchState, draft: ReportDraft) -> tuple[str, int]:
        evidence = state.evidence_store
        footnotes = build_footnote_maps(evidence)
        ref_map = footnotes.evidence_id_to_footnote
        evidence_ids = set(ref_map)
        invalid_references = 0

        lines: list[str] = [
            f"# {state.topic}",
            "",
            f"数据截至：{self._data_as_of(evidence)}",
            "",
            "免责声明：本报告为研究性输出，不构成投资建议。",
            "",
            "## 摘要",
            draft.summary.strip() or self._summary(state, evidence, ref_map),
            "",
            "## 关键发现",
        ]
        for claim in draft.key_findings[:6]:
            rendered, invalid = self._render_claim(claim, ref_map, evidence_ids)
            invalid_references += invalid
            lines.append(f"- {rendered}")

        by_section = {section.sub_question_id: section for section in draft.detailed_analysis}
        lines.extend(["", "## 详细分析"])
        if not state.plan:
            raise ValueError("Cannot render detailed analysis without a plan.")
        for sub_question in state.plan.sub_questions:
            section = by_section.get(sub_question.id)
            lines.append(f"### {sub_question.question}")
            if not section or not section.claims:
                lines.append("当前没有足够证据，需要二次检索补齐。")
                continue
            for claim in section.claims[:3]:
                rendered, invalid = self._render_claim(claim, ref_map, evidence_ids)
                invalid_references += invalid
                lines.append(f"- {rendered}")

        lines.extend(["", "## 风险与限制"])
        if draft.risks:
            for risk in draft.risks[:6]:
                lines.append(f"- {risk}")
        elif state.critic_report and state.critic_report.issues:
            for issue in state.critic_report.issues[:6]:
                affected = ", ".join(issue.affected_claims) or "n/a"
                lines.append(f"- {issue.issue_type} ({issue.severity}): {issue.message} Affected: {affected}.")
        else:
            lines.append("- Critic 未发现高优先级事实、引用或反方观点问题。")

        lines.extend(["", "## 未验证假设"])
        if draft.unverified_assumptions:
            for claim in draft.unverified_assumptions[:4]:
                rendered, invalid = self._render_claim(claim, ref_map, evidence_ids)
                invalid_references += invalid
                lines.append(f"- {rendered}")
        else:
            lines.append("- 本轮报告未单独引入低置信度预测性结论。")

        lines.extend(["", "## 参考来源"])
        for item in footnotes.unique_refs:
            lines.append(
                f"[^{ref_map[item.id]}]: {item.source_title}. {item.source_url} "
                f"({item.source_pub_date.isoformat()})"
            )
        return "\n".join(lines), invalid_references

    def _render_claim(
        self,
        claim: ReportClaim,
        ref_map: dict[str, int],
        evidence_ids: set[str],
    ) -> tuple[str, int]:
        valid_ids: list[str] = []
        invalid_count = 0
        for evidence_id in claim.evidence_ids:
            if evidence_id in evidence_ids:
                valid_ids.append(evidence_id)
            else:
                invalid_count += 1
        citations = " ".join(f"[^{ref_map[evidence_id]}]" for evidence_id in valid_ids)
        text = claim.text.strip()
        return f"{text} {citations}".strip(), invalid_count

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

    def _data_as_of(self, evidence: list[Evidence]) -> str:
        dates = [item.source_pub_date for item in evidence]
        for item in evidence:
            if item.structured_record:
                dates.append(item.structured_record.as_of)
        return max(dates).isoformat() if dates else "未标注"

    def _evidence_claim_text(self, item: Evidence) -> str:
        if item.claim_type != "data" or not item.numeric_fields:
            return item.claim
        fields = item.numeric_fields
        parts = []
        if fields.period:
            parts.append(f"报告期/时点: {fields.period}")
        if fields.dimension:
            parts.append(f"口径: {fields.dimension}")
        if fields.unit:
            parts.append(f"单位: {fields.unit}")
        return f"{item.claim}（{'; '.join(parts)}）" if parts else item.claim
