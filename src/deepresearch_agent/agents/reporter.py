from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.llm import (
    LLMClient,
    LLMClientError,
    LLMRetryExhaustedError,
    StructuredOutputError,
)
from deepresearch_agent.metric_coverage import (
    evaluate_metric_coverage,
    metric_requirements,
)
from deepresearch_agent.reporting import GroundedFactRenderer
from deepresearch_agent.domains.protocols import NumericCitationPolicy, ReportingDomain
from deepresearch_agent.domains.requirements import resolve_domain_capability
from deepresearch_agent.schemas import (
    MAX_REPORT_SECTION_CLAIMS,
    Evidence,
    ReportClaim,
    ReportDraft,
    ResearchState,
    StructuredResearchOutput,
    SubQuestion,
)
from deepresearch_agent.settings import project_root
from deepresearch_agent.structured_output import (
    build_structured_output,
    metric_fact_keys,
)

_RAW_PERIOD_RE = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)")
_RMB_RE = re.compile(
    r"(?<![\d,.])(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*元",
    re.IGNORECASE,
)
_FOOTNOTE_RE = re.compile(r"\[\^(\d+)\]")
# `prompts/reporter.md` requires each numeric fact to be emitted once, and tells
# the reporter not to repeat a key finding *verbatim* in the analysis. R090
# moved the test off the evidence a claim cites and onto the text it states,
# which was the right move; the test it landed on was `\d` -- true of any
# sentence containing a year. Every analysis line about a metric already named
# in `关键发现` matched it, so R099's live runs dropped 2 of 3 analysis claims
# here and the reader received no `## 详细分析` at all.
#
# What the reader loses to a repeat is having already read the sentence, so
# that is what this measures: the claim's content characters against the lines
# already emitted, ignoring digits, punctuation and spacing.
_CONTENT_CHARS_RE = re.compile(r"[\s\d\W_]+", re.UNICODE)
#: Replaces a summary whose figures cannot be bound to Evidence, by sending the
#: reader to the section that carries the bound ones.
FINANCE_SUMMARY_POINTS_TO_FINDINGS = (
    "本报告按权威披露逐项核验题目所列财务指标；"
    "具体数值、同比变化与出处见下方带脚注的关键发现"
    "及指标覆盖状态。"
)
#: R109: smoke2 Q01 shipped the line above over a 关键发现 holding one gap
#: notice and no figure at all -- the summary promised the reader values two
#: lines before the report told them there were none. A pointer to a section is
#: only honest when that section has something to point at.
FINANCE_SUMMARY_NO_CITABLE_VALUE = (
    "本报告按权威披露逐项核验题目所列财务指标，本轮未取得可引用的数值；"
    "各指标的缺口原因与后续核验路径见下方关键发现及指标覆盖状态。"
)
#: Two lines this similar in content characters say the same thing to a reader.
#: Calibrated on the pair the R090 rule was written for -- a key finding and an
#: analysis claim stating one metric's value, which score 0.88.
RESTATEMENT_SIMILARITY = 0.80
def _content_key(text: str) -> str:
    """The characters a reader would recognise again, without the numbers."""

    return _CONTENT_CHARS_RE.sub("", text)


def restates_an_emitted_line(text: str, emitted: list[str]) -> bool:
    """Has the reader already read this sentence?

    Containment covers the case a threshold reads badly on: a short claim whose
    every content character already appears, in order, inside a longer line.
    """

    key = _content_key(text)
    if not key:
        return False
    for line in emitted:
        other = _content_key(line)
        if not other:
            continue
        if key in other or other in key:
            return True
        if SequenceMatcher(None, key, other).ratio() >= RESTATEMENT_SIMILARITY:
            return True
    return False


def render_citations(evidence_ids: list[str], ref_map: dict[str, int]) -> str:
    """Cite each distinct source once, in the order its evidence was selected.

    R107: one footnote covers every Evidence sharing a source URL, so two
    records read out of the same filing both resolve to it. Every site that
    joined markers per evidence id therefore printed the footnote twice -- the
    R107 BYD runs shipped `[^4] [^4]` in 关键发现 and `[^3] [^3]` in 详细分析.
    """

    return " ".join(
        f"[^{number}]"
        for number in dict.fromkeys(
            ref_map[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in ref_map
        )
    )


REPORTER_LLM_MAX_EVIDENCE = 18
REPORTER_LLM_MAX_CLAIM_CHARS = 800
#: The bound the reporter is already held to: `prompts/reporter.md` states it and
#: `ReportSection.claims` enforces it, so a validated draft can never exceed it.
#: Applied per authored section, which makes it a no-op -- and that is the point.
#: The renderer used to re-apply the same number to the *merged* group, where it
#: was the only thing cutting claims: the second R099 live run lost 3 of 6
#: analysis claims to it after the sections were merged.
MAX_ANALYSIS_CLAIMS_PER_SECTION = MAX_REPORT_SECTION_CLAIMS
#: R116: how much Evidence the floor prints for a sub-question the draft passed
#: over. It is a floor, not a dump -- the reference-list explosion R117 handles
#: is what happens when a report prints everything it holds. Measured on the 30
#: R113 states: 2 costs 2.5 reader lines per report against a 32-line body.
MAX_EVIDENCE_FLOOR_CLAIMS = 2
#: Scales a claim may quote a typed value in (raw, 百, 千, 万, 亿, percent).
_FLOOR_SCALE_FACTORS = (
    Decimal(1),
    Decimal("0.01"),
    Decimal(100),
    Decimal(1000),
    Decimal(10000),
    Decimal(100000000),
)
_FLOOR_VALUE_TOLERANCE = Decimal("0.0001")
_CLAIM_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
#: Punctuation and interrogatives carry no topic, and every sub-question ends in
#: some of them, so counting them would score every item alike.
_OVERLAP_STOP_CHARACTERS = frozenset("？?，,。.、；;：:（）()「」“”\"'的了是有和与在对及其如何哪些什么多少怎样为")


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
        numeric_citation_policy: NumericCitationPolicy | None = None,
        domain_pack: ReportingDomain | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.grounded_fact_renderer = grounded_fact_renderer
        self.domain_pack = resolve_domain_capability(
            domain_pack, consumer="ReporterAgent"
        )
        self.numeric_citation_policy = (
            numeric_citation_policy
            or self.domain_pack.numeric_citation_policy()
        )
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
                if (
                    isinstance(exc, LLMRetryExhaustedError)
                    and self.llm_client.fail_on_retry_exhaustion
                ):
                    raise
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
        if self.domain_pack.name != "finance":
            from deepresearch_agent.decisions import append_decision_record

            return append_decision_record(report, state.agent_decisions)
        return self._compact_reader_report(
            report, state, footnotes.evidence_id_to_footnote
        )

    def _compact_reader_report(
        self,
        report: str,
        state: ResearchState,
        ref_map: dict[str, int],
    ) -> str:
        """Drop reader noise without dropping the reporter's actual analysis.

        Web-page excerpts and execution/audit traces remain available in the
        audit bundle.  R087 wrote this to strip everything except mechanically
        grounded facts, which was right while the reporter LLM was truncated
        into its fallback and its ``详细分析`` held deterministic filing
        boilerplate.  With that call working (R090), unconditionally deleting
        the section would discard the only part of the report that answers the
        question in prose, so the section is carried through exactly when the
        reporter did not fall back.  ``补充事实`` stays dropped: it is the
        renderer's bucket for claims unrelated to the question.
        """
        def section(title: str) -> list[str]:
            match = re.search(
                rf"(?ms)^## {re.escape(title)}\s*$\n?(.*?)(?=^## |\Z)",
                report,
            )
            return match.group(1).strip().splitlines() if match else []

        preamble = report.split("## 摘要", 1)[0].rstrip()
        key = section("关键发现")
        coverage = section("指标覆盖状态")
        lines = [preamble, "", "## 摘要"]
        lines.extend(section("摘要")[:1] or ["本报告按权威披露逐项核验所请求指标。"])
        lines.extend(["", "## 关键发现", *key])
        derived = self._gross_margin_derivation(state, ref_map)
        if derived:
            lines.extend(["", *derived])
        detailed = section("详细分析") if self.last_stats.get("fallback") is False else []
        if detailed:
            lines.extend(["", "## 详细分析", *detailed])
        if coverage:
            lines.extend(["", "## 指标覆盖状态", *coverage])
        # Keep only reader-relevant, non-template limitations.  Annual filings
        # are not stale merely because they are older than news articles.
        risks = [
            line for line in section("风险与限制")
            if self.domain_pack.reader_risk_visible(line)
        ]
        if risks and "Critic 未执行" not in risks[0]:
            lines.extend(["", "## 风险与限制", *risks])
        assumptions = [
            line
            for line in section("未验证假设")
            if self.domain_pack.reader_assumption_visible(line)
        ]
        if assumptions and "本轮报告未单独引入" not in assumptions[0]:
            lines.extend(["", "## 未验证假设", *assumptions])
        references = section("参考来源")
        if references:
            lines.extend(["", "## 参考来源", *references])
        return "\n".join(lines).rstrip()

    def _gross_margin_derivation(
        self, state: ResearchState, ref_map: dict[str, int]
    ) -> list[str]:
        """Render the finance domain's first deterministic derived metric."""
        derive = getattr(self.domain_pack, "reader_derived_metrics", None)
        if derive is None:
            return []
        metrics = derive(state.evidence_store)
        if not metrics:
            return []
        # R102: one line per period. Rendering only `metrics[0]` answered a
        # question about change across two years with a single year's ratio.
        lines: list[str] = []
        for metric in metrics:
            evidence_ids = [str(item) for item in metric["evidence_ids"]]
            if len(evidence_ids) != 2 or any(
                item not in ref_map for item in evidence_ids
            ):
                continue
            period = self._reader_text(str(metric.get("period") or "")).strip()
            scope = f"{period} " if period else ""
            citations = render_citations(list(evidence_ids), ref_map)
            lines.append(
                f"- {scope}{metric['label']}（推导值）：{metric['numerator']} / "
                f"{metric['denominator']} = {metric['value']} {citations}"
            )
        if not lines:
            return []
        return ["## 派生指标", *lines]

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
        fidelity_degradations: list[dict[str, str]] = []
        grounded_gaps = list(batch.gaps)
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
            citations = render_citations(valid_ids, ref_map)
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
                grounded_gaps.append(claim.label)
                fidelity_degradations.append(
                    {
                        "label": claim.label,
                        "reason": "grounded_fact_fidelity_failure",
                    }
                )
                continue
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
        # R103: a metric computed from its components is still not directly
        # disclosed, so it stays a gap -- but saying `本轮未作推算` two lines
        # above the section performing that derivation is a report contradicting
        # itself, which R102 introduced by fixing only half of it.
        derived_periods = self.domain_pack.derived_metric_periods(state.evidence_store)
        # R109: a metric the run never found and a metric whose evidence could
        # not be bound to it are different facts, and only the first is
        # `未取得可引用的原始披露事实`. Saying the first about the second put
        # `未取得` in 关键发现 above a 指标覆盖状态 listing thirteen cited values
        # -- the same contradiction, reached by the other road, in 2 of 7 live
        # 长江电力 runs this round. The reader is now told which one happened
        # and where the evidence they were not given is listed.
        unverifiable = {
            item["label"]
            for item in fidelity_degradations
            if item.get("reason") == "grounded_fact_fidelity_failure"
        }
        for label in dict.fromkeys(grounded_gaps):
            if label in unverifiable:
                grounded_lines.append(
                    f"- {label}：已检索到相关披露，但其摘录无法与该指标绑定核验，"
                    "未纳入关键发现；已引用的出处见「指标覆盖状态」。"
                )
                continue
            grounded_lines.append(
                f"- {label}："
                + self.domain_pack.reader_metric_gap_explanation(
                    label, derived_periods.get(label, ())
                )
            )
        lines = lines[:start] + grounded_lines + [""] + lines[end:]
        # Nothing survived to be pointed at, so the summary must stop pointing.
        if not grounded_provenance:
            lines = [
                FINANCE_SUMMARY_NO_CITABLE_VALUE
                if line.strip() == FINANCE_SUMMARY_POINTS_TO_FINDINGS
                else line
                for line in lines
            ]
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
            "grounded_gaps": list(dict.fromkeys(grounded_gaps)),
            "downgraded_numeric_lines": downgraded,
            "mode": "mechanical_typed_evidence",
        }
        if fidelity_degradations:
            state.metadata.setdefault("degradation_events", []).extend(
                {
                    "tool": "grounded_fact_renderer",
                    "impact": "mechanically rendered fact was omitted",
                    "attempts": 1,
                    **degradation,
                }
                for degradation in fidelity_degradations
            )
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
        # R100: one footnote covers every Evidence sharing a source, so this
        # mapping is one-to-many. Built as a dict comprehension it kept only the
        # last, and a line was then checked against whichever fact happened to
        # win -- a margin line citing a footnote whose last entry was a revenue
        # extract could not be supported by it, and was deleted as unverifiable
        # while quoting its own source. `has_numeric_mismatch` already reads its
        # evidence as a union; give it the whole union.
        evidence_by_footnote: dict[int, list[Evidence]] = defaultdict(list)
        evidence_by_id = {item.id: item for item in state.evidence_store}
        for evidence_id, number in ref_map.items():
            item = evidence_by_id.get(evidence_id)
            if item is not None:
                evidence_by_footnote[number].append(item)
        section = ""
        downgraded = 0
        notice_emitted = False
        for index, line in enumerate(lines):
            if line.startswith("## "):
                section = line.removeprefix("## ").strip()
                continue
            if section not in guarded_sections or not line.strip():
                continue
            if line.startswith("### "):
                continue
            cited = [
                item
                for number in _FOOTNOTE_RE.findall(line)
                for item in evidence_by_footnote.get(int(number), ())
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
            notice = "该数值表述未通过 Evidence 保真守卫，无法由引用证据核验，已移除；请参阅关键发现中的可核验数值。"
            # R107: this said the notice once by testing `notice in lines`, but
            # the line it writes carries a `- ` bullet prefix, so that test
            # never matched what it had written and every downgrade printed the
            # sentence again. R105's and R107's live 详细分析 both opened with
            # the same 47-character apology twice in a row. Track what was
            # emitted rather than searching for it in a form it is never
            # stored in.
            if notice_emitted:
                lines[index] = ""
            else:
                lines[index] = prefix + notice
                notice_emitted = True
            downgraded += 1
        return downgraded

    def structured_output(self, state: ResearchState) -> StructuredResearchOutput:
        return build_structured_output(state, self.domain_pack)

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
            for key in metric_fact_keys(evidence, self.domain_pack).get(item.id, set())
        }
        by_subq: dict[str, list[Evidence]] = defaultdict(list)
        for item in evidence:
            by_subq[item.sub_question_id].append(item)

        supplemental: list[Evidence] = []
        analysis_lines: list[str] = []
        for sub_question in state.plan.sub_questions:
            section_lines = [f"### {sub_question.question}"]
            items = by_subq.get(sub_question.id, [])
            if not items:
                section_lines.append("当前没有足够证据，需要二次检索补齐。")
                analysis_lines.extend(section_lines)
                continue
            rendered = 0
            for item in items:
                fact_keys = metric_fact_keys(evidence, self.domain_pack).get(item.id, set())
                if item.id in key_evidence_ids:
                    continue
                if item.id not in key_evidence_ids and not (fact_keys & key_fact_keys):
                    supplemental.append(item)
                    continue
                section_lines.append(f"- {self._evidence_claim_text(item)} [^{ref_map[item.id]}]")
                rendered += 1
            if rendered:
                analysis_lines.extend(section_lines)

        if analysis_lines:
            lines.extend(["", "## 详细分析", *analysis_lines])

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
        prompt_evidence = self._llm_prompt_evidence(evidence)
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
                                    "numeric_fields": item.numeric_fields.model_dump(mode="json")
                                    if item.numeric_fields
                                    else None,
                                }
                                for item in prompt_evidence
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
            "analysis_flow": self.last_stats.get("analysis_flow", {}),
            "dropped_analysis_claims": self.last_stats.get(
                "dropped_analysis_claims", []
            ),
            "repair_attempts": result.repair_attempts,
        }
        return report

    @staticmethod
    def _llm_prompt_evidence(evidence: list[Evidence]) -> list[Evidence]:
        """Keep the reporter's provider payload bounded without mutating state."""

        tier_rank = {"primary": 0, "secondary": 1, "unknown": 2}
        ordered = sorted(
            enumerate(evidence),
            key=lambda item: (tier_rank[item[1].source_tier], -item[1].confidence, item[0]),
        )
        selected: list[Evidence] = []
        for _, item in ordered[:REPORTER_LLM_MAX_EVIDENCE]:
            selected.append(item.model_copy(update={"claim": item.claim[:REPORTER_LLM_MAX_CLAIM_CHARS]}))
        return selected

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
        except (LLMClientError, StructuredOutputError, ValueError) as exc:
            if (
                isinstance(exc, LLMRetryExhaustedError)
                and self.llm_client is not None
                and self.llm_client.fail_on_retry_exhaustion
            ):
                raise
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
        evidence_fact_keys = metric_fact_keys(evidence, self.domain_pack)
        evidence_by_id = {
            item.id: item
            for item in evidence
        }
        required_metrics = {
            item.metric
            for item in metric_requirements(state, self.domain_pack)
        }
        seen_fact_keys: set[tuple[str, str, str, str]] = set()
        # R100: what the reader has already been shown, in the order shown. The
        # repeat test in the analysis loop asks whether a claim says the same
        # thing as one of these, which is the whole of the harm a repeat does.
        emitted_reader_lines: list[str] = []
        key_fact_keys: set[tuple[str, str, str, str]] = set()
        key_evidence_ids: set[str] = set()
        # R116: every Evidence id the reader can actually follow, across all
        # authored sections. `key_evidence_ids` is a topicality signal scoped to
        # 关键发现; this is the coverage question, and the two must not share a
        # variable.
        cited_evidence_ids: set[str] = set()
        supplemental: list[tuple[str, int, ReportClaim]] = []
        financial_contract = bool(metric_requirements(state, self.domain_pack))
        summary = self._reader_text(draft.summary.strip())
        if (
            financial_contract
            and self.numeric_citation_policy.has_numeric_mismatch(summary, [])
        ):
            summary = FINANCE_SUMMARY_POINTS_TO_FINDINGS

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
            emitted_reader_lines.append(rendered)
            seen_fact_keys.update(fact_keys)
            key_fact_keys.update(fact_keys)
            key_evidence_ids.update(
                item for item in claim.evidence_ids if item in evidence_ids
            )
            cited_evidence_ids.update(
                item for item in claim.evidence_ids if item in evidence_ids
            )

        # R099: this was a dict comprehension keyed by `sub_question_id`, so a
        # reporter that answered one sub-question in several themed sections --
        # which `prompts/reporter.md` invites and the live run did, three
        # sections under one id -- had all but the last silently discarded
        # before any of it was looked at. The heading the draft supplies is not
        # rendered anyway (the sub-question's own text is), so sections sharing
        # an id are one section's worth of claims, in the order they arrived.
        # `prompts/reporter.md` promises the renderer keeps at most three claims
        # per section, so the cap belongs to the section the reporter wrote, not
        # to the group they merge into. Applying it after the merge would make
        # answering the prompt in three sections cost two thirds of the answer --
        # the same loss the comprehension used to cause, one step later.
        by_section: dict[str, list[ReportClaim]] = defaultdict(list)
        for section in draft.detailed_analysis:
            by_section[section.sub_question_id].extend(
                section.claims[:MAX_ANALYSIS_CLAIMS_PER_SECTION]
            )
        detailed_lines: list[str] = []
        if not state.plan:
            raise ValueError("Cannot render detailed analysis without a plan.")
        # R099: `reader_analysis_lines` was 0 in all three of R098's live runs,
        # and in the one where the reporter did not fall back there was no way
        # to tell an empty draft from a draft this loop discarded. Every branch
        # below that costs the reader a line is counted, so the next look at a
        # zero starts from a measurement instead of a reading of this function.
        plan_sub_question_ids = {item.id for item in state.plan.sub_questions}
        analysis_flow: dict[str, int] = {
            "draft_sections": len(draft.detailed_analysis),
            "draft_claims": sum(
                len(section.claims) for section in draft.detailed_analysis
            ),
            "sections_unmatched_to_plan": sum(
                1
                for section in draft.detailed_analysis
                if section.sub_question_id not in plan_sub_question_ids
            ),
            "sections_merged_by_shared_id": len(draft.detailed_analysis)
            - len(by_section),
            "claims_in_unmatched_sections": sum(
                len(claims)
                for identifier, claims in by_section.items()
                if identifier not in plan_sub_question_ids
            ),
            "claims_over_section_cap": sum(
                max(0, len(section.claims) - MAX_ANALYSIS_CLAIMS_PER_SECTION)
                for section in draft.detailed_analysis
            ),
            "claims_dropped_unrelated": 0,
            "claims_dropped_duplicate_number": 0,
            "rendered_lines": 0,
        }
        # R100: R099's counters said how many claims each rule consumed but not
        # which, so judging whether a rule was right needed another paid run.
        # The texts are kept beside the counts.
        dropped_claims: list[dict[str, str]] = []
        # R092: relatedness normally means "shares evidence or a fact key with a
        # key finding". That signal disappears when every key finding comes from
        # the structured provider and the analysis cites filing text, because the
        # two can never share an evidence id -- R091 delivered four authored
        # claims and zero analysis lines because of exactly that. Only in that
        # case does citing this sub-question's own evidence stand in for it; when
        # a key finding does cite retrieved text, the original rule still holds
        # and off-topic claims still fall through to 补充事实.
        evidence_by_sub_question: dict[str, set[str]] = defaultdict(set)
        retrieved_ids = {item.id for item in evidence if item.structured_record is None}
        for item in evidence:
            evidence_by_sub_question[item.sub_question_id].add(item.id)
        for sub_question in state.plan.sub_questions:
            section_claims = by_section.get(sub_question.id) or []
            if not section_claims:
                continue
            section_evidence_ids = evidence_by_sub_question[sub_question.id]
            if key_evidence_ids & retrieved_ids & section_evidence_ids:
                section_evidence_ids = set()
            section_lines = [f"### {self._reader_text(sub_question.question)}"]
            rendered_count = 0
            # Already capped per authored section above; capping again here
            # would reintroduce the group-wide cut this change exists to remove.
            for index, claim in enumerate(section_claims):
                fact_keys = self._claim_fact_keys(
                    claim,
                    evidence_fact_keys,
                )
                valid_claim_ids = {
                    item
                    for item in claim.evidence_ids
                    if item in evidence_ids
                }
                # R100: sharing evidence with a key finding is a good topicality
                # signal only while there are grounded key findings to share
                # with. When every required metric came back a gap, the reader's
                # `关键发现` is a list of notices citing nothing, and four claims
                # about this question's own revenue and margin drivers were filed
                # as off-topic and then deleted with `补充事实`. A sentence that
                # names the metric the question asks about is on topic whatever
                # it cites; one that names none still falls through.
                related = bool(
                    valid_claim_ids & (key_evidence_ids | section_evidence_ids)
                    or fact_keys & key_fact_keys
                    or self.domain_pack.metrics_mentioned(
                        claim.text, required_metrics
                    )
                )
                if not related:
                    supplemental.append(
                        (sub_question.id, index, claim)
                    )
                    analysis_flow["claims_dropped_unrelated"] += 1
                    dropped_claims.append(
                        {"reason": "unrelated", "text": claim.text}
                    )
                    continue
                if (
                    fact_keys
                    and fact_keys <= seen_fact_keys
                    and restates_an_emitted_line(claim.text, emitted_reader_lines)
                    and not any(
                        not evidence_fact_keys.get(item)
                        for item in valid_claim_ids
                    )
                ):
                    analysis_flow["claims_dropped_duplicate_number"] += 1
                    dropped_claims.append(
                        {"reason": "duplicate_number", "text": claim.text}
                    )
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
                section_lines.append(f"- {rendered}")
                emitted_reader_lines.append(rendered)
                seen_fact_keys.update(fact_keys)
                cited_evidence_ids.update(valid_claim_ids)
                rendered_count += 1
            if rendered_count:
                detailed_lines.extend(section_lines)
                analysis_flow["rendered_lines"] += rendered_count

        # R116: the draft the model writes is the report -- rendering drops
        # nothing. Measured over the 30 R113 live reports, 8 of 80
        # sub-questions produced evidence and reached the reader with none of
        # it, and 10 of the 50 gold facts were retrieved, extracted, and then
        # never cited. Q16 is the shape of it: nine SNE Research items sat under
        # `share_2024` while the model wrote 「未获取SNE Research等第三方机构的
        # 官方装机量数据」 and answered from revenue instead.
        #
        # The model chooses what to say; it may not choose to say nothing about
        # a question it has evidence for. This floor renders that sub-question's
        # own evidence when none of it was cited, and never competes with an
        # authored claim that did cite it.
        # 补充事实 is rendered before the floor is computed, not before it is
        # printed: a sub-question whose only surviving citation landed here has
        # been answered, and the floor must not repeat it.
        supplemental_lines: list[str] = []
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
            cited_evidence_ids.update(
                item for item in claim.evidence_ids if item in evidence_ids
            )
            supplemental_lines.append(f"- {rendered}")
            emitted_reader_lines.append(rendered)

        floor_sections, floor_count = self._render_evidence_floor(
            state,
            evidence,
            ref_map,
            cited_evidence_ids=cited_evidence_ids,
            claim_provenance=claim_provenance,
        )
        analysis_flow["evidence_floor_lines"] = floor_count
        analysis_flow["evidence_floor_sub_questions"] = len(floor_sections)
        for section_lines in floor_sections:
            detailed_lines.extend(section_lines)

        if detailed_lines:
            lines.extend(["", "## 详细分析", *detailed_lines])

        if supplemental_lines:
            lines.extend(["", "## 补充事实", *supplemental_lines])

        lines.extend(["", "## 风险与限制"])
        if draft.risks:
            for risk in draft.risks[:6]:
                rendered_risk = self._reader_text(risk)
                if (
                    financial_contract
                    and self.numeric_citation_policy.has_numeric_mismatch(
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
                    and self.numeric_citation_policy.has_numeric_mismatch(
                        str(provenance["text"]),
                        claim_evidence,
                        required_metrics=required_metrics,
                    )
                ):
                    citations = render_citations(
                        list(claim.evidence_ids), ref_map
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
        self.last_stats["analysis_flow"] = analysis_flow
        self.last_stats["dropped_analysis_claims"] = dropped_claims
        return "\n".join(lines), invalid_references, missing_reference_backfills

    @staticmethod
    def _question_overlap(sub_question: SubQuestion, item: Evidence) -> int:
        """How many of the sub-question's content characters the claim repeats.

        Deliberately lexical and language-agnostic: the sub-question is the
        agent's own wording, and an item that repeats more of it is more likely
        to be about it. This is a tie-break inside one sub-question's own
        evidence, not a relevance model.
        """

        question = {
            character
            for character in sub_question.question
            if character.strip() and character not in _OVERLAP_STOP_CHARACTERS
        }
        if not question:
            return 0
        return len(question & set(item.claim))

    def _floor_claim_text(self, item: Evidence) -> str:
        """The extractor's own sentence when its number agrees with the typed field.

        R116. `_evidence_claim_text` replaces a data claim with a typed
        re-rendering so a paraphrase can never display a wrong value. It does
        that by discarding the sentence, which also discards everything the
        sentence said besides the value. On the R113 Q08 state the floor pulled
        in an extracted sentence that gave the period total, its change against
        the prior period, and an explicit statement that the question's premise
        did not hold. The typed rendering kept the total and dropped the other
        two -- the parts that answer a question premised on a decline.

        The guarantee that rule protects is that a *disagreeing* value is never
        shown. When the claim's own numbers contain the typed value, there is
        nothing to disagree about, so the sentence is shown as extracted. When
        they do not, the typed rendering still wins.
        """

        typed_value = None
        if item.structured_record is not None:
            typed_value = item.structured_record.value
        elif item.numeric_fields is not None:
            typed_value = item.numeric_fields.value
        if typed_value is None:
            return self._evidence_claim_text(item)
        target = Decimal(str(typed_value))
        for candidate in _CLAIM_NUMBER_RE.finditer(item.claim):
            try:
                stated = Decimal(candidate.group(0).replace(",", ""))
            except InvalidOperation:  # pragma: no cover - regex admits numerals
                continue
            if target == 0:
                if stated == 0:
                    return item.claim
                continue
            for factor in _FLOOR_SCALE_FACTORS:
                # The typed value is scaled, not the stated one: a claim
                # quoting raw units states the same fact as a typed value
                # carrying a magnitude unit.
                scaled = target * factor
                if abs(stated - scaled) <= abs(scaled) * _FLOOR_VALUE_TOLERANCE:
                    return item.claim
        return self._evidence_claim_text(item)

    def _render_evidence_floor(
        self,
        state: ResearchState,
        evidence: list[Evidence],
        ref_map: dict[str, int],
        *,
        cited_evidence_ids: set[str],
        claim_provenance: list[dict[str, object]],
    ) -> tuple[list[list[str]], int]:
        """Render a sub-question's own Evidence when the draft cited none of it.

        R116. The reporter model receives every packed Evidence item and decides
        what to write, and a sub-question it says nothing about is
        indistinguishable, to the reader, from one that returned nothing. On the
        R113 live set that happened to 8 of 80 sub-questions, and it is how the
        four figures that refute Q16's premise were retrieved, extracted, packed
        into the reporter's context, and never printed.

        The floor does not rank, summarise, or reword. It prints the Evidence
        this sub-question already has, highest confidence first, so a question
        with evidence can never reach the reader as silence.
        """

        if not state.plan:
            return [], 0
        by_sub_question: dict[str, list[Evidence]] = defaultdict(list)
        for item in evidence:
            by_sub_question[item.sub_question_id].append(item)
        sections: list[list[str]] = []
        rendered_total = 0
        for sub_question in state.plan.sub_questions:
            items = by_sub_question.get(sub_question.id) or []
            if not items:
                continue
            # R116: confidence alone ranks by how much the provider is trusted,
            # not by whether the item answers this sub-question. Every AKShare
            # row carries 0.98 and every extracted sentence 0.85--0.95, so on
            # the Q16 state a market-share question's floor was two net-profit
            # rows while the SNE Research share figures sat below them. Overlap
            # with the sub-question's own wording is the tie-break the reader
            # needs; confidence still orders items that answer it equally well.
            # Deterministic throughout: overlap, then confidence, then id.
            ordered = sorted(
                items,
                key=lambda item: (
                    -self._question_overlap(sub_question, item),
                    -item.confidence,
                    item.id,
                ),
            )
            # Not "did this sub-question get cited at all" -- that version of
            # the rule closed all 8 orphans on the R113 states and recovered
            # zero gold facts, because the losses were in sub-questions the
            # draft had cited, just not for the evidence that answered them.
            # Q16 cited `share_2024` and still told the reader the SNE figures
            # were not obtained. What the reader is owed is this sub-question's
            # best evidence, whatever else was said about it.
            missing = [
                item
                for item in ordered[:MAX_EVIDENCE_FLOOR_CLAIMS]
                if item.id not in cited_evidence_ids
            ]
            if not missing:
                continue
            section_lines = [f"### {self._reader_text(sub_question.question)}"]
            for item in missing:
                text = self._floor_claim_text(item)
                section_lines.append(f"- {text} [^{ref_map[item.id]}]")
                claim_provenance.append(
                    {
                        "path": f"evidence_floor[{sub_question.id}]",
                        "has_citation": True,
                        "evidence_floor": True,
                    }
                )
                rendered_total += 1
            sections.append(section_lines)
        return sections, rendered_total

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
        citations = render_citations(valid_ids, ref_map)
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

    def _reader_text(
        self,
        text: str,
        *,
        normalize_currency: bool = True,
    ) -> str:
        def readable_rmb(match: re.Match[str]) -> str:
            value = Decimal(match.group(1))
            divisor, unit = (
                (100_000_000, "亿元")
                if abs(value) >= 100_000_000
                else (10_000, "万元")
                if abs(value) >= 10_000
                else (1, "元")
            )
            rendered = f"{value / Decimal(divisor):.4f}".rstrip("0").rstrip(".")
            return f"{rendered}{unit}"

        if normalize_currency:
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
        return max(dates).isoformat() if dates else "未标注"

    def _evidence_claim_text(
        self,
        item: Evidence,
        *,
        require_typed: bool = False,
    ) -> str:
        # Reader-visible data claims must be rendered from typed fields even
        # when a tolerance-based audit considers the generated claim close
        # enough.  The claim remains useful as extraction provenance, but it
        # is not an exact-value display surface.
        if item.claim_type == "data" and (
            item.structured_record
            or (
                item.numeric_fields
                and (
                    require_typed
                    or self._claim_displays_numeric_unit(item)
                )
            )
        ):
            return self._typed_evidence_claim(item)
        if item.claim_type == "data" and item.numeric_fields:
            fields = item.numeric_fields
            parts = []
            if fields.period:
                parts.append(f"报告期/时点: {fields.period}")
            if fields.dimension:
                parts.append(f"口径: {fields.dimension}")
            if fields.unit:
                parts.append(f"单位: {fields.unit}")
            return (
                f"{item.claim}（{'; '.join(parts)}）"
                if parts
                else item.claim
            )
        return item.claim

    def _claim_displays_numeric_unit(self, item: Evidence) -> bool:
        fields = item.numeric_fields
        if not fields or not fields.unit:
            return False
        numeric_value = (
            r"-?(?:\d{1,3}(?:,\d{3})+|\d+)"
            r"(?:\.\d+)?(?:e[+-]?\d+)?"
        )
        return bool(
            re.search(
                rf"{numeric_value}\s*{re.escape(fields.unit)}",
                item.claim,
                re.IGNORECASE,
            )
        )

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
        rendered = format(decimal, ",f")
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
        rendered_value = f"{rendered} {unit}"
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
        coverage = evaluate_metric_coverage(state, self.domain_pack)
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
        # R103: the coverage section carries the same gap wording as 关键发现 and
        # must not contradict the derived value either.
        derived_by_metric = self.domain_pack.derived_metric_periods(
            state.evidence_store
        )
        lines = [report.rstrip(), "", "## 指标覆盖状态", ""]
        for item in coverage:
            periods = (
                f"（请求报告期：{', '.join(item.requested_periods)}）"
                if item.requested_periods
                else ""
            )
            if item.status == "cited":
                rendered: list[str] = []
                # R109: this rendered every matching evidence id. The first live
                # round put thirteen of them on one 1,500-character line -- three
                # distinct published figures for one period, restated once per
                # source that carried them. The domain decides what counts as one
                # published figure; this keeps one rendering of each, so a real
                # disagreement between sources survives and an agreement is
                # stated once.
                seen_figures: set[tuple[str, str]] = set()
                for evidence_id in item.evidence_ids:
                    evidence = evidence_by_id.get(evidence_id)
                    if not evidence or evidence_id not in ref_map:
                        continue
                    figure = self.domain_pack.coverage_figure_key(evidence)
                    if figure in seen_figures:
                        continue
                    seen_figures.add(figure)
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
                        f"{self._reader_text(self._evidence_claim_text(evidence, require_typed=True), normalize_currency=False)}"
                        f"{provenance} [^{ref_map[evidence_id]}]"
                    )
                if rendered:
                    lines.append(
                        f"- {item.metric}{periods}："
                        + "；".join(rendered)
                    )
                    continue
            if item.status == "partially_cited":
                lines.append(
                    f"- {item.metric}{periods}：部分已引用；已覆盖 {', '.join(item.observed_periods) or '未标注期间'}，"
                    f"缺少 {', '.join(item.missing_periods) or '未标注期间'}"
                )
            elif item.status == "unparsable_period":
                lines.append(
                    f"- {item.metric}{periods}：请求报告期无法解析；"
                    f"未执行静默缩窄。缺失 {', '.join(item.missing_periods)}。"
                )
            elif item.status == "searched_unavailable":
                missing = (
                    f"；缺失报告期：{', '.join(item.missing_periods)}"
                    if item.missing_periods
                    else ""
                )
                lines.append(
                    f"- {item.metric}{periods}："
                    + self.domain_pack.reader_metric_gap_explanation(
                        item.metric, derived_by_metric.get(item.metric, ())
                    )
                    + missing
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
