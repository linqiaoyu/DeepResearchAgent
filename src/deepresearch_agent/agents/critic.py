from __future__ import annotations

import itertools
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from deepresearch_agent.schemas import CriticReport, Evidence, Issue, ResearchState, RetryTask
from deepresearch_agent.settings import project_root

NUMBER_RE = re.compile(r"(?P<number>\d+(?:\.\d+)?)\s*(?P<suffix>%|percent|x|倍|万|million|billion)?", re.I)
DATE_RE = re.compile(r"(\d{4}-\d{1,2}(?:-\d{1,2})?|\d{4}年\d{1,2}月(?:\d{1,2}日)?)")


@dataclass(frozen=True)
class NumericClaimKey:
    entity: str
    metric_name: str
    period: str
    dimension: str


class CriticAgent:
    def __init__(
        self,
        today: date | None = None,
        max_source_age_days: int = 365,
        metric_table_path: Path | None = None,
        numeric_relative_tolerance: float = 0.01,
    ) -> None:
        self.today = today or date.today()
        self.max_source_age_days = max_source_age_days
        self.numeric_relative_tolerance = numeric_relative_tolerance
        self.metric_table = self._load_metric_table(
            metric_table_path or project_root() / "data" / "finance_metric_normalization.json"
        )

    def critique(self, state: ResearchState) -> CriticReport:
        issues: list[Issue] = []
        evidence = state.evidence_store
        issues.extend(self._missing_citation_issues(state))
        issues.extend(self._numeric_conflicts(evidence))
        issues.extend(self._temporal_conflicts(evidence))
        issues.extend(self._outdated_sources(evidence))
        issues.extend(self._missing_counterargument(state))
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
                    sub_question_id=sub_question.id,
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
        keyed_claims = [
            (item, key)
            for item in evidence
            if item.claim_type == "data"
            for key in [self._numeric_claim_key(item)]
            if key is not None
        ]
        for (left, left_key), (right, right_key) in itertools.combinations(keyed_claims, 2):
            if left_key != right_key or left.source_url == right.source_url:
                continue
            left_value = left.numeric_fields.value if left.numeric_fields else None
            right_value = right.numeric_fields.value if right.numeric_fields else None
            if left_value is None or right_value is None:
                continue
            if self._meaningfully_different(left_value, right_value):
                official_mismatch = left.source_kind == "structured" or right.source_kind == "structured"
                task = RetryTask(
                    reason=f"Conflicting numeric claims for {left_key.metric_name}",
                    query=f"{left_key.entity} {left_key.metric_name} {left_key.period} official data",
                    source_type="official",
                    sub_question_id=left.sub_question_id,
                    severity="high",
                )
                message = (
                    f"Numeric conflict on {left_key.entity}/{left_key.metric_name}/"
                    f"{left_key.period}/{left_key.dimension}: '{left.claim}' vs '{right.claim}'."
                )
                if official_mismatch:
                    message += " Text claim is inconsistent with structured official data source."
                issues.append(
                    Issue(
                        issue_type="numeric_conflict",
                        severity="high",
                        affected_claims=[left.id, right.id],
                        message=message,
                        suggested_retry_task=task,
                    )
                )
        return issues[:3]

    def _temporal_conflicts(self, evidence: list[Evidence]) -> list[Issue]:
        issues: list[Issue] = []
        dated_claims: list[tuple[Evidence, str, str]] = []
        for item in evidence:
            dates = DATE_RE.findall(item.claim)
            if not dates:
                continue
            event_key = self._temporal_event_key(item.claim)
            if event_key:
                dated_claims.append((item, event_key, dates[0]))
        for (left, left_key, left_date), (right, right_key, right_date) in itertools.combinations(
            dated_claims, 2
        ):
            if left_key != right_key or left_date == right_date or left.source_url == right.source_url:
                continue
            issues.append(
                Issue(
                    issue_type="temporal_conflict",
                    severity="medium",
                    affected_claims=[left.id, right.id],
                    message=(
                        f"Temporal conflict for '{left_key}': '{left_date}' vs '{right_date}'."
                    ),
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
                    sub_question_id=item.sub_question_id,
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

    def _missing_counterargument(self, state: ResearchState) -> list[Issue]:
        evidence = state.evidence_store
        joined = " ".join(item.claim.lower() for item in evidence)
        has_counter = any(term in joined for term in ["risk", "constraint", "however", "compliance", "监管", "limitation"])
        if has_counter:
            return []
        task = RetryTask(
            reason="No counterargument or risk evidence found",
            query="AI agent financial advice risk compliance counterargument",
            source_type="official",
            sub_question_id=self._counterargument_sub_question_id(state),
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

    def _counterargument_sub_question_id(self, state: ResearchState) -> str | None:
        if not state.plan or not state.plan.sub_questions:
            return None
        for sub_question in state.plan.sub_questions:
            lowered = sub_question.id.lower()
            if "risk" in lowered or "governance" in lowered:
                return sub_question.id
        return state.plan.sub_questions[-1].id

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
        return abs(left - right) / denominator > self.numeric_relative_tolerance

    def _numeric_claim_key(self, item: Evidence) -> NumericClaimKey | None:
        fields = item.numeric_fields
        if not fields or not fields.entity or not fields.metric_name or not fields.period:
            return None
        return NumericClaimKey(
            entity=self._normalize_text(fields.entity),
            metric_name=self._normalize_metric(fields.metric_name),
            period=fields.period.strip(),
            dimension=self._normalize_dimension(fields.dimension),
        )

    def _normalize_metric(self, metric_name: str) -> str:
        aliases = self.metric_table.get("metric_aliases", {})
        normalized = metric_name.strip()
        return aliases.get(normalized, normalized)

    def _normalize_dimension(self, dimension: str) -> str:
        aliases = self.metric_table.get("dimension_aliases", {})
        normalized = (dimension or "未标注").strip()
        return aliases.get(normalized, normalized)

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", "", value.strip().lower())

    def _temporal_event_key(self, claim: str) -> str:
        without_dates = DATE_RE.sub("", claim)
        without_numbers = re.sub(r"\d+(?:\.\d+)?", "", without_dates)
        return self._normalize_text(without_numbers)

    def _load_metric_table(self, path: Path) -> dict[str, dict[str, str]]:
        return json.loads(path.read_text(encoding="utf-8"))
