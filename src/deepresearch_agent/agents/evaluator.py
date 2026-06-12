from __future__ import annotations

import re
import time
from collections import Counter

from deepresearch_agent.citations import build_footnote_maps
from deepresearch_agent.schemas import EvaluationResult, Evidence, ResearchState

CITATION_RE = re.compile(r"\[\^(\d+)\]")
WORD_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]{2,}")
SUPPORT_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+")


class Evaluator:
    def evaluate(self, state: ResearchState, started_at: float | None = None) -> EvaluationResult:
        report = state.final_report or ""
        evidence_count = len(state.evidence_store)
        claim_lines = [line for line in report.splitlines() if line.startswith("- ")]
        citation_total, supported_citations, unresolved_citations = self._score_citations(
            claim_lines,
            state.evidence_store,
        )
        citation_resolution_rate = (
            (citation_total - unresolved_citations) / citation_total if citation_total else 0.0
        )
        execution_mode = state.metadata.get("execution_mode")

        if execution_mode == "llm":
            citation_accuracy = None
            citation_accuracy_reason = (
                "Existing citation scorer only applies to extractive output; "
                "paraphrase-aware verification is deferred to the judge task."
            )
            citation_errors = unresolved_citations
            answer_relevance = None
            answer_relevance_reason = "LLM mode requires LLM-as-Judge before reporting answer relevance."
            faithfulness = None
            faithfulness_reason = "LLM mode requires LLM-as-Judge before reporting faithfulness."
        else:
            citation_accuracy = supported_citations / citation_total if citation_total else 0.0
            citation_accuracy_reason = None
            citation_errors = citation_total - supported_citations
            topic_terms = {term.lower() for term in WORD_RE.findall(state.topic)}
            report_terms = {term.lower() for term in WORD_RE.findall(report)}
            answer_relevance = round(len(topic_terms & report_terms) / max(len(topic_terms), 1), 3)
            answer_relevance_reason = None

            cited_claim_lines = [line for line in claim_lines if CITATION_RE.search(line)]
            faithfulness = round(len(cited_claim_lines) / max(len(claim_lines), 1), 3)
            faithfulness_reason = None

        issues = state.critic_report.issues if state.critic_report else []
        bad_case_categories = Counter(issue.issue_type for issue in issues)
        if citation_errors:
            bad_case_categories["citation_error"] += citation_errors
        llm_stats = state.metadata.get("llm_stats", {})
        extractor_stats = llm_stats.get("extractor", []) if isinstance(llm_stats, dict) else []
        invalid_extract_text = sum(int(item.get("invalid_extract_text", 0)) for item in extractor_stats)
        if invalid_extract_text:
            bad_case_categories["invalid_extract_text"] += invalid_extract_text
        reporter_stats = llm_stats.get("reporter", {}) if isinstance(llm_stats, dict) else {}
        invalid_references = int(reporter_stats.get("invalid_references", 0))
        if invalid_references:
            bad_case_categories["citation_reference_error"] += invalid_references
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
            task_success_rate=1.0 if state.final_report and evidence_count else 0.0,
            citation_accuracy=round(citation_accuracy, 3) if citation_accuracy is not None else None,
            citation_accuracy_reason=citation_accuracy_reason,
            citation_resolution_rate=round(citation_resolution_rate, 3),
            critic_catch_rate=round(critic_catch_rate, 3),
            answer_relevance=answer_relevance,
            answer_relevance_reason=answer_relevance_reason,
            faithfulness=faithfulness,
            faithfulness_reason=faithfulness_reason,
            latency_seconds=round(latency_seconds, 3),
            cost_usd=round(state.cost_used, 4),
            cost_cny=cost_cny,
            price_source=price_source,
            token_used=state.token_used,
            bad_case_categories=dict(bad_case_categories),
        )

    def _score_citations(
        self,
        claim_lines: list[str],
        evidence_store: list[Evidence],
    ) -> tuple[int, int, int]:
        footnote_to_evidence = build_footnote_maps(evidence_store).footnote_to_evidence
        citation_total = 0
        supported_citations = 0
        unresolved_citations = 0

        for line in claim_lines:
            citation_numbers = [int(match) for match in CITATION_RE.findall(line)]
            if not citation_numbers:
                continue

            claim_text = self._claim_text(line)
            for citation_number in citation_numbers:
                citation_total += 1
                evidence = footnote_to_evidence.get(citation_number)
                if not evidence:
                    unresolved_citations += 1
                    continue
                if self._is_supported(claim_text, evidence):
                    supported_citations += 1

        return citation_total, supported_citations, unresolved_citations

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
