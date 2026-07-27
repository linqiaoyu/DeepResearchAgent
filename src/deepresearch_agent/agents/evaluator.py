from __future__ import annotations

import re
import time
from collections import Counter

from deepresearch_agent.domains.protocols import NumericCitationPolicy
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.semantic_judge import (
    SemanticJudge,
    SemanticJudgeFailure,
    SemanticJudgeScore,
)
from deepresearch_agent.llm.client import BudgetExceededError, CostOverrunError
from deepresearch_agent.metric_coverage import metric_requirements
from deepresearch_agent.schemas import EvaluationResult, Evidence, ResearchState
from deepresearch_agent.trajectory import TrajectoryCacheMissError

CITATION_RE = re.compile(r"\[\^(\d+)\]")
WORD_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]{2,}")
SUPPORT_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+")


class Evaluator:
    def __init__(
        self,
        *,
        semantic_judge: SemanticJudge | None = None,
        semantic_judge_enabled: bool | None = None,
        numeric_citation_policy: NumericCitationPolicy | None = None,
    ) -> None:
        self.semantic_judge = semantic_judge
        self.semantic_judge_enabled = (
            semantic_judge is not None
            if semantic_judge_enabled is None
            else semantic_judge_enabled
        )
        self.numeric_citation_policy = (
            numeric_citation_policy
            or load_domain_pack("finance").numeric_citation_policy()
        )

    def evaluate(self, state: ResearchState, started_at: float | None = None) -> EvaluationResult:
        report = state.final_report or ""
        evidence_count = len(state.evidence_store)
        required_metrics = {
            item.metric
            for item in metric_requirements(state)
        }
        claim_lines = [line for line in report.splitlines() if line.startswith("- ")]
        execution_mode = state.metadata.get("execution_mode")
        (
            citation_total,
            supported_citations,
            unresolved_citations,
            _bullet_numeric_mismatches,
        ) = self._score_citations(
            claim_lines,
            state.evidence_store,
            state.report_footnote_evidence,
            required_metrics,
        )
        numeric_citation_mismatches = self._numeric_report_mismatches(
            report,
            state.evidence_store,
            state.report_footnote_evidence,
            required_metrics,
        )
        if citation_total and not state.report_footnote_evidence:
            state.metadata.setdefault("degradation_events", []).append(
                {
                    "tool": "citation_mapping",
                    "reason": "report_footnote_evidence_missing",
                    "impact": (
                        "citation resolution and deterministic citation accuracy "
                        "are unavailable; positional inference is prohibited"
                    ),
                    "attempts": 1,
                }
            )
        citation_resolution_rate = (
            (citation_total - unresolved_citations) / citation_total if citation_total else 0.0
        )
        paged_numeric_evidence = [
            item
            for item in state.evidence_store
            if item.numeric_fields is not None and item.source_page is not None
        ]
        if paged_numeric_evidence:
            bbox_resolution_rate = round(
                sum(item.bbox is not None for item in paged_numeric_evidence)
                / len(paged_numeric_evidence),
                3,
            )
            bbox_resolution_reason = None
        else:
            bbox_resolution_rate = None
            bbox_resolution_reason = "no_paged_numeric_evidence"

        answer_completeness = None
        answer_shape = None
        if execution_mode == "llm":
            citation_errors = unresolved_citations
            semantic_score, semantic_reason = self._semantic_score(state)
            if semantic_score is None:
                citation_accuracy = None
                citation_accuracy_reason = semantic_reason
                answer_completeness_reason = semantic_reason
                answer_relevance = None
                answer_relevance_reason = semantic_reason
                answer_shape_reason = semantic_reason
                faithfulness = None
                faithfulness_reason = semantic_reason
            else:
                citation_accuracy = min(
                    semantic_score.citation_support,
                    citation_resolution_rate,
                )
                citation_accuracy_reason = (
                    semantic_score.citation_support_reason
                )
                if citation_accuracy < semantic_score.citation_support:
                    citation_accuracy_reason += (
                        " Score capped by mechanical citation resolution rate."
                    )
                if numeric_citation_mismatches:
                    citation_accuracy = 0.0
                    citation_accuracy_reason += (
                        " Mechanical numeric audit found a citation mismatch; "
                        "numeric correctness is not delegated to the judge."
                    )
                answer_completeness = round(
                    semantic_score.answer_completeness,
                    3,
                )
                answer_completeness_reason = (
                    semantic_score.answer_completeness_reason
                )
                answer_relevance = round(
                    semantic_score.answer_relevance,
                    3,
                )
                answer_relevance_reason = (
                    semantic_score.answer_relevance_reason
                )
                answer_shape = round(semantic_score.answer_shape, 3)
                answer_shape_reason = semantic_score.answer_shape_reason
                faithfulness = round(semantic_score.faithfulness, 3)
                faithfulness_reason = semantic_score.faithfulness_reason
        else:
            citation_accuracy = supported_citations / citation_total if citation_total else 0.0
            citation_accuracy_reason = None
            citation_errors = citation_total - supported_citations
            answer_completeness_reason = None
            topic_terms = {term.lower() for term in WORD_RE.findall(state.topic)}
            report_terms = {term.lower() for term in WORD_RE.findall(report)}
            answer_relevance = round(len(topic_terms & report_terms) / max(len(topic_terms), 1), 3)
            answer_relevance_reason = None
            answer_shape_reason = None

            cited_claim_lines = [line for line in claim_lines if CITATION_RE.search(line)]
            faithfulness = round(len(cited_claim_lines) / max(len(claim_lines), 1), 3)
            faithfulness_reason = None

        issues = state.critic_report.issues if state.critic_report else []
        bad_case_categories = Counter(issue.issue_type for issue in issues)
        if citation_errors:
            bad_case_categories["citation_error"] += citation_errors
        if numeric_citation_mismatches:
            bad_case_categories["numeric_citation_mismatch"] += numeric_citation_mismatches
        llm_stats = state.metadata.get("llm_stats", {})
        extractor_stats = llm_stats.get("extractor", []) if isinstance(llm_stats, dict) else []
        invalid_extract_text = sum(int(item.get("invalid_extract_text", 0)) for item in extractor_stats)
        if invalid_extract_text:
            bad_case_categories["invalid_extract_text"] += invalid_extract_text
        reporter_stats = llm_stats.get("reporter", {}) if isinstance(llm_stats, dict) else {}
        invalid_references = int(reporter_stats.get("invalid_references", 0))
        if invalid_references:
            bad_case_categories["citation_reference_error"] += invalid_references
        citation_repair_retry_rate = 1.0 if int(reporter_stats.get("citation_repair_retries", 0) or 0) else 0.0
        claim_provenance = reporter_stats.get("claim_provenance", [])
        if isinstance(claim_provenance, list) and claim_provenance:
            uncited_claims = sum(1 for item in claim_provenance if not item.get("has_citation"))
            uncited_claim_rate = uncited_claims / len(claim_provenance)
        else:
            uncited_claims = int(reporter_stats.get("uncited_claims", 0) or 0)
            claim_count = int(reporter_stats.get("claim_count", 0) or 0)
            uncited_claim_rate = uncited_claims / claim_count if claim_count else 0.0
        critic_catch_rate = min(1.0, len(issues) / 3) if issues else 1.0
        latency_seconds = 0.0 if started_at is None else max(0.0, time.perf_counter() - started_at)
        llm_usage = state.metadata.get("llm_usage", {})
        cost_cny = None
        price_source = None
        if isinstance(llm_usage, dict):
            cost_cny_value = llm_usage.get("total_cost_cny")
            cost_cny = round(float(cost_cny_value), 8) if cost_cny_value is not None else None
            price_source_value = llm_usage.get("price_source")
            price_source = str(price_source_value) if price_source_value else None

        return EvaluationResult(
            research_id=state.research_id,
            task_success_rate=(
                1.0
                if state.final_report and evidence_count and not numeric_citation_mismatches
                else 0.0
            ),
            citation_accuracy=round(citation_accuracy, 3) if citation_accuracy is not None else None,
            citation_accuracy_reason=citation_accuracy_reason,
            citation_resolution_rate=round(citation_resolution_rate, 3),
            bbox_resolution_rate=bbox_resolution_rate,
            bbox_resolution_reason=bbox_resolution_reason,
            citation_repair_retry_rate=round(citation_repair_retry_rate, 3),
            uncited_claim_rate=round(uncited_claim_rate, 3),
            critic_catch_rate=round(critic_catch_rate, 3),
            answer_completeness=answer_completeness,
            answer_completeness_reason=answer_completeness_reason,
            answer_relevance=answer_relevance,
            answer_relevance_reason=answer_relevance_reason,
            answer_shape=answer_shape,
            answer_shape_reason=answer_shape_reason,
            faithfulness=faithfulness,
            faithfulness_reason=faithfulness_reason,
            latency_seconds=round(latency_seconds, 3),
            cost_usd=(round(state.cost_used, 4) if cost_cny is not None else None),
            cost_cny=cost_cny,
            price_source=price_source,
            token_used=(state.token_used if cost_cny is not None else None),
            operational_measurement=(
                "llm_ledger" if cost_cny is not None else "unavailable"
            ),
            bad_case_categories=dict(bad_case_categories),
        )

    def refresh_operational_metrics(
        self,
        result: EvaluationResult,
        state: ResearchState,
    ) -> EvaluationResult:
        """Refresh usage after an optional judge call writes to the ledger."""

        llm_usage = state.metadata.get("llm_usage", {})
        cost_cny = None
        price_source = None
        if isinstance(llm_usage, dict):
            cost_cny_value = llm_usage.get("total_cost_cny")
            cost_cny = (
                round(float(cost_cny_value), 8)
                if cost_cny_value is not None
                else None
            )
            price_source_value = llm_usage.get("price_source")
            price_source = (
                str(price_source_value) if price_source_value else None
            )
        return result.model_copy(
            update={
                "cost_usd": (
                    round(state.cost_used, 4) if cost_cny is not None else None
                ),
                "cost_cny": cost_cny,
                "price_source": price_source,
                "token_used": state.token_used if cost_cny is not None else None,
                "operational_measurement": (
                    "llm_ledger" if cost_cny is not None else "unavailable"
                ),
            }
        )

    def _semantic_score(
        self,
        state: ResearchState,
    ) -> tuple[SemanticJudgeScore | None, str | None]:
        if not self.semantic_judge_enabled:
            reason = (
                "semantic_judge_disabled: set SEMANTIC_JUDGE_ENABLED=true "
                "to measure LLM report semantics."
            )
            state.metadata["semantic_judge"] = {
                "status": "disabled",
                "reason": "semantic_judge_disabled",
            }
            return None, reason
        if self.semantic_judge is None:
            reason = (
                "semantic_judge_unavailable: enabled without a configured "
                "typed judge client."
            )
            state.metadata["semantic_judge"] = {
                "status": "unavailable",
                "reason": "semantic_judge_unavailable",
            }
            return None, reason
        try:
            score = self.semantic_judge.score(state)
            if not isinstance(score, SemanticJudgeScore):
                raise SemanticJudgeFailure("invalid_typed_output")
        except (
            BudgetExceededError,
            CostOverrunError,
            TrajectoryCacheMissError,
        ):
            raise
        except Exception as exc:
            error_type = (
                exc.error_type
                if isinstance(exc, SemanticJudgeFailure)
                else type(exc).__name__
            )
            reason = f"semantic_judge_failed: {error_type}"
            state.metadata["semantic_judge"] = {
                "status": "failed",
                "reason": "semantic_judge_failed",
                "error_type": error_type,
            }
            state.metadata.setdefault("degradation_events", []).append(
                {
                    "tool": "semantic_judge",
                    "reason": "semantic_judge_failed",
                    "impact": (
                        "semantic evaluation metrics are unavailable; "
                        "mechanical numeric audit remains authoritative"
                    ),
                    "attempts": 1,
                    "error_type": error_type,
                }
            )
            return None, reason
        state.metadata["semantic_judge"] = {
            "status": "scored",
            "scope": (
                "completeness,relevance,answer_shape,citation_support,"
                "faithfulness; numeric correctness excluded"
            ),
        }
        return score, None

    def _score_citations(
        self,
        claim_lines: list[str],
        evidence_store: list[Evidence],
        report_footnote_evidence: dict[int, str] | None = None,
        required_metrics: set[str] | None = None,
    ) -> tuple[int, int, int, int]:
        evidence_by_id = {item.id: item for item in evidence_store}
        footnote_to_evidence = {
            number: evidence_by_id[evidence_id]
            for number, evidence_id in (report_footnote_evidence or {}).items()
            if evidence_id in evidence_by_id
        }
        citation_total = 0
        supported_citations = 0
        unresolved_citations = 0
        numeric_citation_mismatches = 0

        for line in claim_lines:
            citation_numbers = [int(match) for match in CITATION_RE.findall(line)]
            if not citation_numbers:
                continue

            claim_text = self._claim_text(line)
            cited_evidence = [
                footnote_to_evidence[citation_number]
                for citation_number in citation_numbers
                if citation_number in footnote_to_evidence
            ]
            numeric_mismatch = (
                bool(cited_evidence)
                and self.numeric_citation_policy.has_numeric_mismatch(
                    claim_text,
                    cited_evidence,
                    required_metrics=required_metrics,
                )
            )
            if numeric_mismatch:
                numeric_citation_mismatches += 1
            for citation_number in citation_numbers:
                citation_total += 1
                evidence = footnote_to_evidence.get(citation_number)
                if not evidence:
                    unresolved_citations += 1
                    continue
                if not numeric_mismatch and self._is_supported(claim_text, evidence):
                    supported_citations += 1

        return (
            citation_total,
            supported_citations,
            unresolved_citations,
            numeric_citation_mismatches,
        )

    def _numeric_report_mismatches(
        self,
        report: str,
        evidence_store: list[Evidence],
        report_footnote_evidence: dict[int, str] | None,
        required_metrics: set[str] | None = None,
    ) -> int:
        """Audit every reader-visible financial number, including the summary."""
        evidence_by_id = {item.id: item for item in evidence_store}
        footnote_to_evidence = {
            number: evidence_by_id[evidence_id]
            for number, evidence_id in (
                report_footnote_evidence or {}
            ).items()
            if evidence_id in evidence_by_id
        }
        mismatches = 0
        for raw_line in report.splitlines():
            line = raw_line.strip()
            if (
                not line
                or line.startswith("#")
                or re.match(r"^\[\^\d+\]:", line)
            ):
                continue
            citation_numbers = [
                int(match)
                for match in CITATION_RE.findall(line)
            ]
            cited_evidence = [
                footnote_to_evidence[number]
                for number in citation_numbers
                if number in footnote_to_evidence
            ]
            claim_text = CITATION_RE.sub("", line.removeprefix("- ")).strip()
            if self.numeric_citation_policy.has_numeric_mismatch(
                claim_text,
                cited_evidence,
                required_metrics=required_metrics,
            ):
                mismatches += 1
        return mismatches

    def _claim_text(self, line: str) -> str:
        text = line.removeprefix("- ").strip()
        return CITATION_RE.sub("", text).strip()

    def _is_supported(self, claim_text: str, evidence: Evidence) -> bool:
        for support_text in (evidence.claim, evidence.extract_text):
            if self._has_substring_support(claim_text, support_text):
                return True

            claim_tokens = self._support_tokens(claim_text)
            support_tokens = self._support_tokens(support_text)
            if not claim_tokens or not support_tokens:
                continue

            overlap = len(claim_tokens & support_tokens)
            precision = overlap / len(claim_tokens)
            min_overlap = 2 if len(claim_tokens) <= 4 else 3
            if overlap >= min_overlap and precision >= 0.6:
                return True

        return False

    def _has_substring_support(self, claim_text: str, support_text: str) -> bool:
        claim_norm = self._normalize_text(claim_text)
        support_norm = self._normalize_text(support_text)
        if len(claim_norm) < 12 or len(support_norm) < 12:
            return False
        return claim_norm in support_norm or support_norm in claim_norm

    def _normalize_text(self, text: str) -> str:
        return "".join(SUPPORT_TOKEN_RE.findall(text.lower()))

    def _support_tokens(self, text: str) -> set[str]:
        tokens: set[str] = set()
        for match in SUPPORT_TOKEN_RE.findall(text.lower()):
            if re.fullmatch(r"[\u4e00-\u9fff]+", match):
                if len(match) == 1:
                    tokens.add(match)
                else:
                    tokens.update(match[index : index + 2] for index in range(len(match) - 1))
            elif len(match) > 1 or match.isdigit():
                tokens.add(match)
        return tokens
