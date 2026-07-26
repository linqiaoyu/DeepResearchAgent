from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.decisions import append_decision_record
from deepresearch_agent.llm import LLMClient, LLMClientError, StructuredOutputError
from deepresearch_agent.metric_coverage import (
    evaluate_metric_coverage,
    metric_requirements,
)
from deepresearch_agent.reporting import GroundedFactRenderer
from deepresearch_agent.agents.numeric_citations import (
    has_financial_numeric_mismatch,
)
from deepresearch_agent.schemas import (
    Evidence,
    ReportClaim,
    ReportDraft,
    ResearchState,
    StructuredResearchOutput,
)
from deepresearch_agent.settings import project_root
from deepresearch_agent.structured_output import (
    build_structured_output,
    metric_fact_keys,
)

_RAW_PERIOD_RE = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")
_RMB_RE = re.compile(
    r"(?<![\d,])(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*元",
    re.IGNORECASE,
)
_FOOTNOTE_RE = re.compile(r"\[\^(\d+)\]")


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
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        grounded_fact_renderer: GroundedFactRenderer | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.grounded_fact_renderer = grounded_fact_renderer
        self.last_stats: dict[str, object] = {}

    def report(
        self,
        state: ResearchState,
        *,
        context_evidence: list[Evidence] | None = None,
    ) -> str:
        if not state.plan:
            raise ValueError("Cannot report before planning.")
        footnotes = build_footnote_maps(state.evidence_store)
        state.report_footnote_evidence = {
            number: evidence.id
            for number, evidence in footnotes.footnote_to_evidence.items()
        }
        if self.llm_client:
            try:
                report = (
                    self._llm_report(state)
                    if context_evidence is None
                    else self._llm_report(
                        state,
                        context_evidence=context_evidence,
                    )
                )
            except (LLMClientError, StructuredOutputError, ValueError) as exc:
                self.last_stats = {"fallback": True, "error_type": type(exc).__name__}
                report = self._deterministic_report(state)
        else:
            report = self._deterministic_report(state)
        report = self._enforce_reader_fidelity(
            report,
            state,
            footnotes.evidence_id_to_footnote,
        )
        report = self._append_metric_coverage(
            report,
            state,
            footnotes.evidence_id_to_footnote,
        )
        return append_decision_record(report, state.agent_decisions)

    def _enforce_reader_fidelity(
        self,
        report: str,
        state: ResearchState,
        ref_map: dict[str, int],
    ) -> str:
        """Replace key facts with typed rendering and fail closed elsewhere."""

        if not self.grounded_fact_renderer:
            return report
        batch = self.grounded_fact_renderer.render(state)
        grounded = batch.claims
        if not batch.required_labels:
            return report
        required_labels = set(batch.required_labels)
        claim_labels = [claim.label for claim in grounded]
        gap_labels = set(batch.gaps)
        if (
            len(claim_labels) != len(set(claim_labels))
            or set(claim_labels) & gap_labels
            or set(claim_labels) | gap_labels != required_labels
        ):
            raise ValueError(
                "grounded fact renderer returned a partial or ambiguous batch"
            )
        lines = report.splitlines()
        start = next(
            (
                index
                for index, line in enumerate(lines)
                if line.strip() == "## 关键发现"
            ),
            None,
        )
        if start is None:
            raise ValueError(
                "reader fidelity guard requires a key findings section"
            )
        end = next(
            (
                index
                for index in range(start + 1, len(lines))
                if lines[index].startswith("## ")
            ),
            len(lines),
        )
        grounded_lines = ["## 关键发现", ""]
        grounded_provenance: list[dict[str, object]] = []
        evidence_by_id = {item.id: item for item in state.evidence_store}
        for index, claim in enumerate(grounded):
            valid_ids = [
                evidence_id
                for evidence_id in claim.evidence_ids
                if evidence_id in ref_map
            ]
            if (
                not valid_ids
                or tuple(valid_ids) != claim.evidence_ids
                or not claim.fact_keys
            ):
                raise ValueError(
                    "grounded fact renderer returned an unbound claim: "
                    f"{claim.label}"
                )
            citations = " ".join(
                f"[^{ref_map[evidence_id]}]"
                for evidence_id in valid_ids
            )
            rendered = f"{claim.text.rstrip()} {citations}".strip()
            cited_evidence = [
                evidence_by_id[evidence_id]
                for evidence_id in valid_ids
            ]
            if not self.grounded_fact_renderer.is_supported(
                rendered,
                cited_evidence,
                state,
                labels={claim.label},
            ):
                raise ValueError(
                    "mechanically rendered fact failed its Evidence fidelity "
                    f"contract: {claim.label}"
                )
            grounded_lines.append(f"- {rendered}")
            grounded_provenance.append(
                {
                    "path": f"key_findings:grounded:{index}",
                    "text": claim.text,
                    "provenance": "mechanical_grounded_fact",
                    "evidence_ids": valid_ids,
                    "has_citation": bool(valid_ids),
                    "invalid_reference_count": 0,
                    "mutation_guarded": True,
                    "label": claim.label,
                }
            )
        for label in batch.gaps:
            grounded_lines.append(
                f"- {label}：未取得满足 typed coverage 与 Evidence "
                "保真合同的事实；本轮不展示生成式数值结论。"
            )
        lines = lines[:start] + grounded_lines + [""] + lines[end:]
        downgraded = self._downgrade_unsupported_numeric_lines(
            lines,
            state,
            ref_map,
            required_labels,
        )
        prior = self.last_stats.get("claim_provenance", [])
        prior_rows = prior if isinstance(prior, list) else []
        self.last_stats["claim_provenance"] = [
            item
            for item in prior_rows
            if not str(item.get("path", "")).startswith("key_findings:")
        ] + grounded_provenance
        self.last_stats["reader_fidelity_guard"] = {
            "grounded_key_findings": len(grounded),
            "grounded_gaps": list(batch.gaps),
            "downgraded_numeric_lines": downgraded,
            "mode": "mechanical_typed_evidence",
        }
        return "\n".join(lines)

    def _downgrade_unsupported_numeric_lines(
        self,
        lines: list[str],
        state: ResearchState,
        ref_map: dict[str, int],
        required_labels: set[str],
    ) -> int:
        guarded_sections = {
            "摘要",
            "详细分析",
            "补充事实",
            "风险与限制",
            "未验证假设",
        }
        evidence_by_footnote = {
            number: evidence
            for evidence_id, number in ref_map.items()
            for evidence in state.evidence_store
            if evidence.id == evidence_id
        }
        section = ""
        downgraded = 0
        for index, line in enumerate(lines):
            if line.startswith("## "):
                section = line.removeprefix("## ").strip()
                continue
            if section not in guarded_sections or not line.strip():
                continue
            if line.startswith("### "):
                continue
            cited = [
                evidence_by_footnote[int(number)]
                for number in _FOOTNOTE_RE.findall(line)
                if int(number) in evidence_by_footnote
            ]
            if self.grounded_fact_renderer is None:
                raise ValueError("reader fidelity policy disappeared mid-run")
            if self.grounded_fact_renderer.is_supported(
                line,
                cited,
                state,
                labels=required_labels,
            ):
                continue
            prefix = "- " if line.lstrip().startswith("-") else ""
            lines[index] = (
                prefix
                + "该数值表述未通过 Evidence 保真守卫，已从读者报告移除；"
                "精确值仅以“关键发现”和“指标覆盖状态”的机械渲染为准。"
            )
            downgraded += 1
        return downgraded

    def structured_output(self, state: ResearchState) -> StructuredResearchOutput:
        return build_structured_output(state)

    def _deterministic_report(self, state: ResearchState) -> str:
        evidence = state.evidence_store
        footnotes = build_footnote_maps(evidence)
        ref_map = footnotes.evidence_id_to_footnote
        show_source_tiers = any(
            item.source_tier != "unknown" or item.content_truncated
            for item in evidence
        )
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

        key_evidence_ids = {item.id for item in evidence[:6]}
        key_fact_keys = {
            key
            for item in evidence[:6]
            for key in metric_fact_keys(evidence).get(item.id, set())
        }
        by_subq: dict[str, list[Evidence]] = defaultdict(list)
        for item in evidence:
            by_subq[item.sub_question_id].append(item)

        supplemental: list[Evidence] = []
        lines.extend(["", "## 详细分析"])
        for sub_question in state.plan.sub_questions:
            lines.append(f"### {sub_question.question}")
            items = by_subq.get(sub_question.id, [])
            if not items:
                lines.append("当前没有足够证据，需要二次检索补齐。")
                continue
            rendered = 0
            for item in items:
                fact_keys = metric_fact_keys(evidence).get(item.id, set())
                if item.id in key_evidence_ids:
                    continue
                if item.id not in key_evidence_ids and not (fact_keys & key_fact_keys):
                    supplemental.append(item)
                    continue
                lines.append(f"- {self._evidence_claim_text(item)} [^{ref_map[item.id]}]")
                rendered += 1
            if not rendered:
                lines.append("本节没有可追溯到关键发现的新增分析项。")

        if supplemental:
            lines.extend(["", "## 补充事实"])
            for item in supplemental:
                lines.append(f"- {self._evidence_claim_text(item)} [^{ref_map[item.id]}]")

        lines.extend(["", "## 风险与限制"])
        if state.critic_report and state.critic_report.issues:
            for issue in state.critic_report.issues[:6]:
                affected = self._affected_claims(
                    issue.affected_claims,
                    ref_map,
                    stable=bool(
                        state.metadata.get(
                            "stable_reader_evidence_refs"
                        )
                    ),
                )
                lines.append(f"- {issue.issue_type} ({issue.severity}): {issue.message} Affected: {affected}.")
        else:
            lines.append("- Critic 未执行；本轮不提供质量判断。")

        projections = [item for item in evidence if item.claim_type == "projection"]
        lines.extend(["", "## 未验证假设"])
        if projections:
            for item in projections[:4]:
                lines.append(f"- {item.claim} [^{ref_map[item.id]}]")
        else:
            lines.append("- 本轮报告未单独引入低置信度预测性结论。")

        lines.extend(["", "## 参考来源"])
        for item in footnotes.unique_refs:
            provenance = (
                f" [source_tier={item.source_tier}]"
                + (
                    " [content_truncated=true]"
                    if item.content_truncated
                    else ""
                )
                if show_source_tiers
                else ""
            )
            lines.append(
                f"[^{ref_map[item.id]}]: {item.source_title}. {item.source_url} "
                f"({item.source_pub_date.isoformat() if item.source_pub_date else 'unknown'})"
                f"{f' [page={item.source_page}]' if item.source_page else ''}{provenance}"
            )
        return "\n".join(lines)

    def _llm_report(
        self,
        state: ResearchState,
        *,
        context_evidence: list[Evidence] | None = None,
    ) -> str:
        assert self.llm_client is not None
        prompt = (project_root() / "prompts" / "reporter.md").read_text(encoding="utf-8")
        # The context packer is an LLM prompt budget, not an Evidence-store
        # mutation. Rendering, footnotes, fidelity and structured output keep
        # using the canonical state below.
        evidence = (
            context_evidence
            if context_evidence is not None
            else state.evidence_store
        )
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
                                    "source_pub_date": item.source_pub_date.isoformat() if item.source_pub_date else "unknown",
                                    "source_page": item.source_page,
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
            evidence_catalog=evidence,
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
        evidence_catalog: list[Evidence],
    ) -> tuple[ReportDraft, dict[str, int | list[str]]]:
        assert self.llm_client is not None
        # Citation repair is part of the same generation envelope as the first
        # Reporter call.  Reusing the bounded view prevents a retry from
        # silently bypassing the working-memory prompt budget.  Rendering and
        # footnotes still use canonical state.evidence_store.
        evidence_ids = {item.id for item in evidence_catalog}
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
                                    for item in evidence_catalog
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
        show_source_tiers = any(
            item.source_tier != "unknown" or item.content_truncated
            for item in evidence
        )
        evidence_ids = set(ref_map)
        invalid_references = 0
        missing_reference_backfills = 0
        claim_provenance: list[dict[str, object]] = []
        repaired_claim_keys = repaired_claim_keys or set()
        evidence_fact_keys = metric_fact_keys(evidence)
        evidence_by_id = {
            item.id: item
            for item in evidence
        }
        required_metrics = {
            item.metric
            for item in metric_requirements(state)
        }
        seen_fact_keys: set[tuple[str, str, str, str]] = set()
        key_fact_keys: set[tuple[str, str, str, str]] = set()
        key_evidence_ids: set[str] = set()
        supplemental: list[tuple[str, int, ReportClaim]] = []
        financial_contract = bool(metric_requirements(state))
        summary = self._reader_text(draft.summary.strip())
        if (
            financial_contract
            and has_financial_numeric_mismatch(summary, [])
        ):
            summary = (
                "本报告按权威披露逐项核验题目所列财务指标；"
                "具体数值、同比变化与出处见下方带脚注的关键发现"
                "及指标覆盖状态。"
            )

        lines: list[str] = [
            f"# {self._reader_text(state.topic)}",
            "",
            f"数据截至：{self._data_as_of(evidence)}",
            "",
            "免责声明：本报告为研究性输出，不构成投资建议。",
            "",
            "## 摘要",
            summary or self._summary(state, evidence, ref_map),
            "",
            "## 关键发现",
        ]
        for index, claim in enumerate(draft.key_findings[:6]):
            fact_keys = self._claim_fact_keys(claim, evidence_fact_keys)
            if fact_keys and fact_keys <= seen_fact_keys:
                continue
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
            seen_fact_keys.update(fact_keys)
            key_fact_keys.update(fact_keys)
            key_evidence_ids.update(
                item for item in claim.evidence_ids if item in evidence_ids
            )

        by_section = {section.sub_question_id: section for section in draft.detailed_analysis}
        lines.extend(["", "## 详细分析"])
        if not state.plan:
            raise ValueError("Cannot render detailed analysis without a plan.")
        for sub_question in state.plan.sub_questions:
            section = by_section.get(sub_question.id)
            lines.append(f"### {self._reader_text(sub_question.question)}")
            if not section or not section.claims:
                lines.append("本节没有可追溯到关键发现的分析项。")
                continue
            rendered_count = 0
            for index, claim in enumerate(section.claims[:3]):
                fact_keys = self._claim_fact_keys(
                    claim,
                    evidence_fact_keys,
                )
                valid_claim_ids = {
                    item
                    for item in claim.evidence_ids
                    if item in evidence_ids
                }
                related = bool(
                    valid_claim_ids & key_evidence_ids
                    or fact_keys & key_fact_keys
                )
                if not related:
                    supplemental.append(
                        (sub_question.id, index, claim)
                    )
                    continue
                if (
                    fact_keys
                    and fact_keys <= seen_fact_keys
                    and not any(
                        not evidence_fact_keys.get(item)
                        for item in valid_claim_ids
                    )
                ):
                    continue
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
                seen_fact_keys.update(fact_keys)
                rendered_count += 1
            if not rendered_count:
                lines.append("本节没有可追溯到关键发现的新增分析项。")

        if supplemental:
            lines.extend(["", "## 补充事实"])
            for sub_question_id, index, claim in supplemental:
                path = _ClaimPath(
                    "supplemental_facts",
                    index,
                    sub_question_id,
                )
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
                rendered_risk = self._reader_text(risk)
                if (
                    financial_contract
                    and has_financial_numeric_mismatch(
                        rendered_risk,
                        [],
                    )
                ):
                    rendered_risk = (
                        "该风险原文包含未绑定 Evidence 的财务数字，"
                        "已降级为定性提示；数值结论仅以下方带脚注"
                        "条目为准。"
                    )
                lines.append(f"- {rendered_risk}")
        elif state.critic_report and state.critic_report.issues:
            for issue in state.critic_report.issues[:6]:
                affected = self._affected_claims(
                    issue.affected_claims,
                    ref_map,
                    stable=bool(
                        state.metadata.get(
                            "stable_reader_evidence_refs"
                        )
                    ),
                )
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
                claim_evidence = [
                    evidence_by_id[evidence_id]
                    for evidence_id in claim.evidence_ids
                    if evidence_id in evidence_by_id
                ]
                if (
                    financial_contract
                    and has_financial_numeric_mismatch(
                        str(provenance["text"]),
                        claim_evidence,
                        required_metrics=required_metrics,
                    )
                ):
                    citations = " ".join(
                        f"[^{ref_map[evidence_id]}]"
                        for evidence_id in claim.evidence_ids
                        if evidence_id in ref_map
                    )
                    rendered = (
                        "该假设原文包含未由所引 Evidence 支持的财务数字，"
                        "已降级为定性提示，不作为数值结论。"
                        f"{f' {citations}' if citations else ''}"
                    )
                    provenance["numeric_downgraded"] = True
                claim_provenance.append(provenance)
                lines.append(f"- {rendered}")
        else:
            lines.append("- 本轮报告未单独引入低置信度预测性结论。")

        lines.extend(["", "## 参考来源"])
        for item in footnotes.unique_refs:
            provenance = (
                f" [source_tier={item.source_tier}]"
                + (
                    " [content_truncated=true]"
                    if item.content_truncated
                    else ""
                )
                if show_source_tiers
                else ""
            )
            lines.append(
                f"[^{ref_map[item.id]}]: {item.source_title}. {item.source_url} "
                f"({item.source_pub_date.isoformat() if item.source_pub_date else 'unknown'})"
                f"{f' [page={item.source_page}]' if item.source_page else ''}{provenance}"
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
        text = self._reader_text(claim.text.strip())
        provenance = {
            "path": path.key,
            "text": text,
            "provenance": "repaired" if path.key in repaired_claim_keys else "first_pass",
            "evidence_ids": valid_ids,
            "has_citation": bool(valid_ids),
            "invalid_reference_count": invalid_count,
        }
        return f"{text} {citations}".strip(), invalid_count, backfilled, provenance

    def _claim_fact_keys(
        self,
        claim: ReportClaim,
        evidence_fact_keys: dict[
            str,
            set[tuple[str, str, str, str]],
        ],
    ) -> set[tuple[str, str, str, str]]:
        return {
            key
            for evidence_id in claim.evidence_ids
            for key in evidence_fact_keys.get(evidence_id, set())
        }

    def _reader_text(self, text: str) -> str:
        def readable_rmb(match: re.Match[str]) -> str:
            value = float(match.group(1))
            divisor, unit = (
                (100_000_000, "亿元")
                if abs(value) >= 100_000_000
                else (10_000, "万元")
                if abs(value) >= 10_000
                else (1, "元")
            )
            rendered = f"{value / divisor:.4f}".rstrip("0").rstrip(".")
            return f"{rendered}{unit}"

        text = _RMB_RE.sub(readable_rmb, text)
        return _RAW_PERIOD_RE.sub(
            lambda match: (
                f"{match.group(1)}年{int(match.group(2))}月"
                f"{int(match.group(3))}日"
            ),
            text,
        )

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
        quality_text = (
            f"当前 Critic 质量分为 {state.critic_report.overall_quality:.2f}，"
            if state.critic_report
            else "Critic 未执行，未提供质量分，"
        )
        return (
            f"本报告围绕“{state.topic}”拆解为 {len(state.plan.sub_questions) if state.plan else 0} 个子问题，"
            f"累计抽取 {len(evidence)} 条证据。{quality_text}"
            f"首要结论可追溯到来源 [^{ref_map[first.id]}]。"
        )

    def _data_as_of(self, evidence: list[Evidence]) -> str:
        dates = [item.source_pub_date for item in evidence if item.source_pub_date]
        for item in evidence:
            if item.structured_record:
                dates.append(item.structured_record.as_of)
        return max(dates).isoformat() if dates else "未标注"

    def _evidence_claim_text(self, item: Evidence) -> str:
        if item.claim_type == "data" and item.structured_record:
            return self._typed_evidence_claim(item)
        if item.claim_type != "data" or not item.numeric_fields:
            return item.claim
        if has_financial_numeric_mismatch(item.claim, [item]):
            return self._typed_evidence_claim(item)
        fields = item.numeric_fields
        parts = []
        if fields.period:
            parts.append(f"报告期/时点: {fields.period}")
        if fields.dimension:
            parts.append(f"口径: {fields.dimension}")
        if fields.unit:
            parts.append(f"单位: {fields.unit}")
        return f"{item.claim}（{'; '.join(parts)}）" if parts else item.claim

    def _typed_evidence_claim(self, item: Evidence) -> str:
        record = item.structured_record
        fields = item.numeric_fields
        entity = record.entity if record else fields.entity if fields else ""
        metric = (
            record.metric_name
            if record
            else fields.metric_name
            if fields and fields.metric_name
            else "该指标"
        )
        period = record.period if record else fields.period if fields else ""
        dimension = (
            record.dimension
            if record
            else fields.dimension
            if fields
            else "未标注"
        )
        value = record.value if record else fields.value if fields else None
        unit = record.unit if record else fields.unit if fields else ""
        if value is None or not unit:
            return "该 Evidence 的 typed 数值字段不完整，未展示生成式数值。"
        decimal = Decimal(str(value))
        rendered_value = (
            f"{format(decimal, 'f')}元"
            if unit == "元"
            else f"{format(decimal, 'f').rstrip('0').rstrip('.')}{unit}"
        )
        context = "; ".join(
            part
            for part in (
                f"报告期/时点: {period}" if period else "",
                f"口径: {dimension}" if dimension else "",
                f"单位: {unit}" if unit else "",
            )
            if part
        )
        claim = f"{entity} {period} {dimension}{metric}为{rendered_value}".strip()
        return f"{claim}（{context}）" if context else claim

    def _append_metric_coverage(
        self,
        report: str,
        state: ResearchState,
        ref_map: dict[str, int],
    ) -> str:
        coverage = evaluate_metric_coverage(state)
        if not coverage:
            return report
        state.metadata["requested_metric_coverage"] = [
            item.model_dump(mode="json")
            for item in coverage
        ]
        evidence_by_id = {
            item.id: item
            for item in state.evidence_store
        }
        lines = [report.rstrip(), "", "## 指标覆盖状态", ""]
        for item in coverage:
            periods = (
                f"（请求报告期：{', '.join(item.requested_periods)}）"
                if item.requested_periods
                else ""
            )
            if item.status == "cited":
                rendered: list[str] = []
                for evidence_id in item.evidence_ids:
                    evidence = evidence_by_id.get(evidence_id)
                    if not evidence or evidence_id not in ref_map:
                        continue
                    provenance = (
                        f"，年报 p{evidence.source_page}"
                        if evidence.source_page
                        else (
                            "，接口/字段 "
                            f"{evidence.structured_record.data_source}."
                            f"{evidence.structured_record.metric_name}"
                            if evidence.structured_record
                            else ""
                        )
                    )
                    rendered.append(
                        f"{self._reader_text(self._evidence_claim_text(evidence))}"
                        f"{provenance} [^{ref_map[evidence_id]}]"
                    )
                if rendered:
                    lines.append(
                        f"- {item.metric}{periods}："
                        + "；".join(rendered)
                    )
                    continue
            if item.status == "searched_unavailable":
                missing = (
                    f"；缺失报告期：{', '.join(item.missing_periods)}"
                    if item.missing_periods
                    else ""
                )
                availability = (
                    "已取得部分证据，但未获得可引用的完整指标或同比证据"
                    if item.evidence_ids
                    else "已检索，但未获得可引用的完整指标证据"
                )
                lines.append(
                    f"- {item.metric}{periods}：{availability}{missing}。"
                )
            else:
                lines.append(
                    f"- {item.metric}{periods}：未完成检索；运行在该指标"
                    "检索完成前终止。"
                )
        return "\n".join(lines)

    def _affected_claims(
        self,
        affected_claims: list[str],
        ref_map: dict[str, int],
        *,
        stable: bool,
    ) -> str:
        if not affected_claims:
            return "n/a"
        if not stable:
            return ", ".join(affected_claims)
        return ", ".join(
            (
                f"footnote-{ref_map[item]}"
                if item in ref_map
                else "non-evidence-claim"
            )
            for item in affected_claims
        )
