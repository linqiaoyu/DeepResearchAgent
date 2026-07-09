from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass

from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.llm import LLMClient, LLMClientError, StructuredOutputError
from deepresearch_agent.schemas import Evidence, ReportClaim, ReportDraft, ResearchState
from deepresearch_agent.settings import project_root


@dataclass(frozen=True)
class _ClaimPath:
    section: str
    index: int
    sub_question_id: str | None = None

    @property
    def key(self) -> str:
        if self.sub_question_id:
            return f"{self.section}:{self.sub_question_id}:{self.index}"
        return f"{self.section}:{self.index}"


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
        draft, repair_stats = self._repair_missing_evidence_ids(
            state=state,
            prompt=prompt,
            original_draft=result.parsed,
        )
        report, invalid_reference_count, missing_reference_backfills = self._render_llm_report(
            state,
            draft,
            repaired_claim_keys=set(repair_stats["repaired_claim_keys"]),
        )
        self.last_stats = {
            "fallback": False,
            "invalid_references": invalid_reference_count,
            "missing_reference_backfills": missing_reference_backfills,
            "citation_repair_retries": repair_stats["citation_repair_retries"],
            "citation_repair_candidate_claims": repair_stats["citation_repair_candidate_claims"],
            "citation_repaired_claims": repair_stats["citation_repaired_claims"],
            "claim_count": repair_stats["claim_count"],
            "uncited_claims": repair_stats["uncited_claims"],
            "claim_provenance": self.last_stats.get("claim_provenance", []),
            "repair_attempts": result.repair_attempts,
        }
        return report

    def _repair_missing_evidence_ids(
        self,
        *,
        state: ResearchState,
        prompt: str,
        original_draft: ReportDraft,
    ) -> tuple[ReportDraft, dict[str, int | list[str]]]:
        assert self.llm_client is not None
        evidence_ids = {item.id for item in state.evidence_store}
        original_claims = self._draft_claims(original_draft)
        repair_candidates = [
            {"path": path.key, "text": claim.text, "evidence_ids": claim.evidence_ids}
            for path, claim in original_claims
            if not self._valid_evidence_ids(claim, evidence_ids)
        ]
        stats: dict[str, int | list[str]] = {
            "citation_repair_retries": 0,
            "citation_repair_candidate_claims": len(repair_candidates),
            "citation_repaired_claims": 0,
            "claim_count": len(original_claims),
            "uncited_claims": len(repair_candidates),
            "repaired_claim_keys": [],
        }
        if not repair_candidates:
            return original_draft, stats

        try:
            repair_result = self.llm_client.complete(
                role="reporter",
                run_id=state.research_id,
                schema=ReportDraft,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "task": "repair_missing_evidence_ids",
                                "instructions": [
                                    "Return the same ReportDraft content with evidence_ids repaired.",
                                    "Only use evidence ids from evidence_catalog.",
                                    "Do not invent evidence ids.",
                                    "Do not delete key conclusions just to avoid citations.",
                                    "If no evidence directly supports a claim, leave evidence_ids empty.",
                                ],
                                "missing_or_invalid_claims": repair_candidates,
                                "original_draft": original_draft.model_dump(mode="json"),
                                "evidence_catalog": [
                                    {
                                        "id": item.id,
                                        "claim": item.claim,
                                        "extract_text": item.extract_text,
                                        "source_title": item.source_title,
                                        "source_url": item.source_url,
                                    }
                                    for item in state.evidence_store
                                ],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            )
        except (LLMClientError, StructuredOutputError, ValueError):
            return original_draft, stats

        if not isinstance(repair_result.parsed, ReportDraft):
            return original_draft, stats

        repaired_draft = repair_result.parsed
        repaired_claims = {path.key: claim for path, claim in self._draft_claims(repaired_draft)}
        repaired_keys: list[str] = []
        for item in repair_candidates:
            key = str(item["path"])
            claim = repaired_claims.get(key)
            if claim and self._valid_evidence_ids(claim, evidence_ids):
                repaired_keys.append(key)
        post_repair_uncited = sum(
            1 for _, claim in self._draft_claims(repaired_draft) if not self._valid_evidence_ids(claim, evidence_ids)
        )
        stats.update(
            {
                "citation_repair_retries": 1,
                "citation_repaired_claims": len(repaired_keys),
                "claim_count": len(self._draft_claims(repaired_draft)),
                "uncited_claims": post_repair_uncited,
                "repaired_claim_keys": repaired_keys,
            }
        )
        return repaired_draft, stats

    def _render_llm_report(
        self,
        state: ResearchState,
        draft: ReportDraft,
        repaired_claim_keys: set[str] | None = None,
    ) -> tuple[str, int, int]:
        evidence = state.evidence_store
        footnotes = build_footnote_maps(evidence)
        ref_map = footnotes.evidence_id_to_footnote
        evidence_ids = set(ref_map)
        invalid_references = 0
        missing_reference_backfills = 0
        claim_provenance: list[dict[str, object]] = []
        repaired_claim_keys = repaired_claim_keys or set()

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
        for index, claim in enumerate(draft.key_findings[:6]):
            path = _ClaimPath("key_findings", index)
            rendered, invalid, backfilled, provenance = self._render_claim(
                claim,
                ref_map,
                evidence_ids,
                path=path,
                repaired_claim_keys=repaired_claim_keys,
            )
            invalid_references += invalid
            missing_reference_backfills += backfilled
            claim_provenance.append(provenance)
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
            for index, claim in enumerate(section.claims[:3]):
                path = _ClaimPath("detailed_analysis", index, sub_question.id)
                rendered, invalid, backfilled, provenance = self._render_claim(
                    claim,
                    ref_map,
                    evidence_ids,
                    path=path,
                    repaired_claim_keys=repaired_claim_keys,
                )
                invalid_references += invalid
                missing_reference_backfills += backfilled
                claim_provenance.append(provenance)
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
            for index, claim in enumerate(draft.unverified_assumptions[:4]):
                path = _ClaimPath("unverified_assumptions", index)
                rendered, invalid, backfilled, provenance = self._render_claim(
                    claim,
                    ref_map,
                    evidence_ids,
                    path=path,
                    repaired_claim_keys=repaired_claim_keys,
                )
                invalid_references += invalid
                missing_reference_backfills += backfilled
                claim_provenance.append(provenance)
                lines.append(f"- {rendered}")
        else:
            lines.append("- 本轮报告未单独引入低置信度预测性结论。")

        lines.extend(["", "## 参考来源"])
        for item in footnotes.unique_refs:
            lines.append(
                f"[^{ref_map[item.id]}]: {item.source_title}. {item.source_url} "
                f"({item.source_pub_date.isoformat()})"
            )
        self.last_stats["claim_provenance"] = claim_provenance
        return "\n".join(lines), invalid_references, missing_reference_backfills

    def _render_claim(
        self,
        claim: ReportClaim,
        ref_map: dict[str, int],
        evidence_ids: set[str],
        *,
        path: _ClaimPath,
        repaired_claim_keys: set[str],
    ) -> tuple[str, int, int, dict[str, object]]:
        valid_ids: list[str] = []
        invalid_count = 0
        for evidence_id in claim.evidence_ids:
            if evidence_id in evidence_ids:
                valid_ids.append(evidence_id)
            else:
                invalid_count += 1
        backfilled = 0
        citations = " ".join(f"[^{ref_map[evidence_id]}]" for evidence_id in valid_ids)
        text = claim.text.strip()
        provenance = {
            "path": path.key,
            "text": text,
            "provenance": "repaired" if path.key in repaired_claim_keys else "first_pass",
            "evidence_ids": valid_ids,
            "has_citation": bool(valid_ids),
            "invalid_reference_count": invalid_count,
        }
        return f"{text} {citations}".strip(), invalid_count, backfilled, provenance

    def _draft_claims(self, draft: ReportDraft) -> list[tuple[_ClaimPath, ReportClaim]]:
        claims: list[tuple[_ClaimPath, ReportClaim]] = []
        for index, claim in enumerate(draft.key_findings[:6]):
            claims.append((_ClaimPath("key_findings", index), claim))
        for section in draft.detailed_analysis:
            for index, claim in enumerate(section.claims[:3]):
                claims.append((_ClaimPath("detailed_analysis", index, section.sub_question_id), claim))
        for index, claim in enumerate(draft.unverified_assumptions[:4]):
            claims.append((_ClaimPath("unverified_assumptions", index), claim))
        return claims

    def _valid_evidence_ids(self, claim: ReportClaim, evidence_ids: set[str]) -> list[str]:
        return [evidence_id for evidence_id in claim.evidence_ids if evidence_id in evidence_ids]

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
