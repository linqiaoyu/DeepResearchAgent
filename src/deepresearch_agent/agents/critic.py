from __future__ import annotations

import itertools
import re
from datetime import date

from deepresearch_agent.schemas import CriticReport, Evidence, Issue, ResearchState, RetryTask

NUMBER_RE = re.compile(r"(?P<number>\d+(?:\.\d+)?)\s*(?P<suffix>%|percent|x|倍|万|million|billion)?", re.I)


class CriticAgent:
    def __init__(self, today: date | None = None, max_source_age_days: int = 365) -> None:
        self.today = today or date(2026, 5, 24)
        self.max_source_age_days = max_source_age_days

    def critique(self, state: ResearchState) -> CriticReport:
        issues: list[Issue] = []
        evidence = state.evidence_store
        issues.extend(self._missing_citation_issues(state))
        issues.extend(self._numeric_conflicts(evidence))
        issues.extend(self._outdated_sources(evidence))
        issues.extend(self._missing_counterargument(evidence))
        issues.extend(self._unverified_projections(evidence))

        retry_tasks = [issue.suggested_retry_task for issue in issues if issue.suggested_retry_task]
        high_count = sum(1 for issue in issues if issue.severity == "high")
        medium_count = sum(1 for issue in issues if issue.severity == "medium")
        quality = max(0.0, 1.0 - high_count * 0.15 - medium_count * 0.04)
        return CriticReport(
            passed=high_count == 0,
            overall_quality=round(quality, 3),
            issues=issues,
            retry_tasks=retry_tasks,
            iteration=state.critic_iteration + 1,
        )

    def _missing_citation_issues(self, state: ResearchState) -> list[Issue]:
        if not state.plan:
            return []
        issues: list[Issue] = []
        evidence_by_subq = {item.sub_question_id for item in state.evidence_store}
        for sub_question in state.plan.sub_questions:
            if sub_question.id not in evidence_by_subq:
                task = RetryTask(
                    reason=f"No evidence collected for {sub_question.id}",
                    query=f"{sub_question.question} official source",
                    source_type="official",
                    severity="high",
                )
                issues.append(
                    Issue(
                        issue_type="missing_citation",
                        severity="high",
                        affected_claims=[sub_question.id],
                        message=f"Sub-question '{sub_question.question}' has no source-backed evidence.",
                        suggested_retry_task=task,
                    )
                )
        return issues

    def _numeric_conflicts(self, evidence: list[Evidence]) -> list[Issue]:
        issues: list[Issue] = []
        data_claims = [item for item in evidence if item.claim_type == "data"]
        for left, right in itertools.combinations(data_claims, 2):
            left_key = self._numeric_topic_key(left.claim)
            right_key = self._numeric_topic_key(right.claim)
            if not left_key or left_key != right_key or left.source_url == right.source_url:
                continue
            left_numbers = self._numbers(left.claim)
            right_numbers = self._numbers(right.claim)
            if not left_numbers or not right_numbers:
                continue
            if self._meaningfully_different(left_numbers[0], right_numbers[0]):
                task = RetryTask(
                    reason=f"Conflicting numeric claims for {left_key}",
                    query=f"{left_key} official latest benchmark",
                    source_type="official",
                    severity="high",
                )
                issues.append(
                    Issue(
                        issue_type="numeric_conflict",
                        severity="high",
                        affected_claims=[left.id, right.id],
                        message=f"Numeric conflict on '{left_key}': '{left.claim}' vs '{right.claim}'.",
                        suggested_retry_task=task,
                    )
                )
        return issues[:3]

    def _outdated_sources(self, evidence: list[Evidence]) -> list[Issue]:
        issues: list[Issue] = []
        for item in evidence:
            age_days = (self.today - item.source_pub_date).days
            if age_days <= self.max_source_age_days:
                continue
            if item.claim_type in {"data", "projection"}:
                task = RetryTask(
                    reason="Time-sensitive claim uses an old source",
                    query=f"{item.claim[:80]} latest 2026",
                    source_type="official",
                    severity="medium",
                )
                issues.append(
                    Issue(
                        issue_type="outdated_source",
                        severity="medium",
                        affected_claims=[item.id],
                        message=f"Source '{item.source_title}' is {age_days} days old for a time-sensitive claim.",
                        suggested_retry_task=task,
                    )
                )
        return issues[:5]

    def _missing_counterargument(self, evidence: list[Evidence]) -> list[Issue]:
        joined = " ".join(item.claim.lower() for item in evidence)
        has_counter = any(term in joined for term in ["risk", "constraint", "however", "compliance", "监管", "limitation"])
        if has_counter:
            return []
        task = RetryTask(
            reason="No counterargument or risk evidence found",
            query="AI agent financial advice risk compliance counterargument",
            source_type="official",
            severity="high",
        )
        return [
            Issue(
                issue_type="missing_counterargument",
                severity="high",
                affected_claims=[],
                message="The evidence set lacks a counterargument or risk perspective.",
                suggested_retry_task=task,
            )
        ]

    def _unverified_projections(self, evidence: list[Evidence]) -> list[Issue]:
        issues: list[Issue] = []
        for item in evidence:
            if item.claim_type == "projection" and item.confidence < 0.7:
                issues.append(
                    Issue(
                        issue_type="unverified_projection",
                        severity="medium",
                        affected_claims=[item.id],
                        message=f"Projection claim has low extraction confidence: {item.claim}",
                    )
                )
        return issues

    def _numeric_topic_key(self, claim: str) -> str | None:
        lowered = claim.lower()
        keys = {
            "advisor productivity": ["advisor productivity", "productivity", "效率"],
            "aum growth": ["aum", "assets under management", "资产管理"],
            "cost": ["cost", "成本", "$"],
            "latency": ["latency", "seconds", "秒"],
            "citation accuracy": ["citation accuracy", "引用准确率"],
        }
        for key, markers in keys.items():
            if any(marker in lowered for marker in markers):
                return key
        return None

    def _numbers(self, claim: str) -> list[float]:
        return [float(match.group("number")) for match in NUMBER_RE.finditer(claim)]

    def _meaningfully_different(self, left: float, right: float) -> bool:
        if left == right:
            return False
        denominator = max(abs(left), abs(right), 1.0)
        return abs(left - right) / denominator >= 0.2 and abs(left - right) >= 5
