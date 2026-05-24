from __future__ import annotations

import re
import time
from collections import Counter

from deepresearch_agent.schemas import EvaluationResult, ResearchState

CITATION_RE = re.compile(r"\[\^(\d+)\]")
WORD_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]{2,}")


class Evaluator:
    def evaluate(self, state: ResearchState, started_at: float | None = None) -> EvaluationResult:
        report = state.final_report or ""
        citations = [int(match) for match in CITATION_RE.findall(report)]
        evidence_count = len(state.evidence_store)
        valid_citations = sum(1 for citation in citations if 1 <= citation <= evidence_count)
        citation_accuracy = valid_citations / len(citations) if citations else 0.0

        topic_terms = {term.lower() for term in WORD_RE.findall(state.topic)}
        report_terms = {term.lower() for term in WORD_RE.findall(report)}
        answer_relevance = len(topic_terms & report_terms) / max(len(topic_terms), 1)

        claim_lines = [line for line in report.splitlines() if line.startswith("- ")]
        cited_claim_lines = [line for line in claim_lines if CITATION_RE.search(line)]
        faithfulness = len(cited_claim_lines) / max(len(claim_lines), 1)

        issues = state.critic_report.issues if state.critic_report else []
        bad_case_categories = Counter(issue.issue_type for issue in issues)
        critic_catch_rate = min(1.0, len(issues) / 3) if issues else 1.0
        latency_seconds = 0.0 if started_at is None else max(0.0, time.perf_counter() - started_at)

        return EvaluationResult(
            research_id=state.research_id,
            task_success_rate=1.0 if state.final_report and evidence_count else 0.0,
            citation_accuracy=round(citation_accuracy, 3),
            critic_catch_rate=round(critic_catch_rate, 3),
            answer_relevance=round(answer_relevance, 3),
            faithfulness=round(faithfulness, 3),
            latency_seconds=round(latency_seconds, 3),
            cost_usd=round(state.cost_used, 4),
            token_used=state.token_used,
            bad_case_categories=dict(bad_case_categories),
        )

