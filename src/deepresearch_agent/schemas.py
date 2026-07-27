from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StructuredDataRequest(StrictModel):
    capability: str
    company_name: str | None = None
    symbol: str | None = None
    periods: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def require_parseable_financial_periods(self) -> StructuredDataRequest:
        """Reject ambiguous financial periods before a plan can narrow scope."""
        if self.capability != "financial_indicators":
            return self
        unparsable = [
            period for period in self.periods if _calendar_year(period) is None
        ]
        if unparsable:
            raise ValueError(
                "financial_indicators periods must contain a calendar year or "
                f"YYYYMMDD date; unparsable_periods={unparsable}"
            )
        return self


def _calendar_year(value: str | None) -> str | None:
    """Parse the generic calendar-year forms accepted by the request schema."""
    rendered = (value or "").strip()
    if re.fullmatch(r"20\d{6}", rendered):
        return rendered[:4]
    match = re.search(r"(?<!\d)(20\d{2})(?!\d)", rendered)
    return match.group(1) if match else None


class SubQuestion(StrictModel):
    id: str
    question: str
    search_queries: list[str]
    expected_source_types: list[str] = Field(default_factory=list)
    structured_data_requests: list[StructuredDataRequest] = Field(default_factory=list)
    priority: int = Field(default=3, ge=1, le=5)


class ResearchPlan(StrictModel):
    topic: str
    depth_level: int = Field(default=2, ge=1, le=3)
    sub_questions: list[SubQuestion]
    estimated_sources: int = Field(default=6, ge=1)
    success_criteria: list[str] = Field(default_factory=list)


class BoundingBox(StrictModel):
    page: int = Field(ge=1)
    x0: float = Field(ge=0)
    top: float = Field(ge=0)
    x1: float = Field(ge=0)
    bottom: float = Field(ge=0)


class TextBoundingBox(StrictModel):
    text: str
    bbox: BoundingBox


class Source(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    url: str
    source_type: str
    published_at: date | None = None
    content: str
    credibility: float = Field(default=0.8, ge=0, le=1)
    source_tier: Literal["primary", "secondary", "unknown"] = Field(
        default="unknown",
        exclude_if=lambda value: value == "unknown",
    )
    content_truncated: bool = Field(default=False, exclude_if=lambda value: not value)
    bbox_index: list[TextBoundingBox] = Field(default_factory=list)
    table_index: list[list[list[str | None]]] = Field(default_factory=list)


class SearchRecord(StrictModel):
    query: str
    source_ids: list[str] = Field(default_factory=list)
    latency_ms: int = 0


class SymbolInfo(StrictModel):
    entity: str
    symbol: str
    exchange: str = "A股"
    name: str
    data_source: str
    as_of: date


class StructuredDataRecord(StrictModel):
    entity: str
    symbol: str
    metric_name: str
    period: str
    dimension: str
    value: Decimal
    unit: str
    data_source: str
    as_of: date


class NumericFields(StrictModel):
    entity: str | None = None
    metric_name: str | None = None
    period: str | None = None
    dimension: str = "未标注"
    # This mirror is consumed by numeric guards, so it must preserve the same
    # source value as StructuredDataRecord rather than reintroduce float loss.
    value: Decimal | None = None
    unit: str | None = None


class Evidence(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    research_id: str
    sub_question_id: str
    claim: str
    claim_type: Literal["fact", "opinion", "data", "projection"]
    source_kind: Literal["text", "structured"] = "text"
    source_url: str
    source_title: str
    source_pub_date: date | None = None
    source_page: int | None = Field(default=None, ge=1)
    bbox: BoundingBox | None = None
    extract_text: str
    extract_offset_start: int = 0
    confidence: float = Field(default=0.75, ge=0, le=1)
    source_tier: Literal["primary", "secondary", "unknown"] = Field(
        default="unknown",
        exclude_if=lambda value: value == "unknown",
    )
    content_truncated: bool = Field(default=False, exclude_if=lambda value: not value)
    structured_record: StructuredDataRecord | None = None
    numeric_fields: NumericFields | None = None
    numeric_fields_incomplete: bool = False
    injection_risk_score: float = Field(default=0.0, ge=0, le=1)
    injection_patterns: list[str] = Field(default_factory=list)
    extracted_at: datetime = Field(default_factory=utc_now)


class ExtractedClaim(StrictModel):
    claim: str
    claim_type: Literal["fact", "opinion", "data", "projection"]
    source_url: str
    extract_text: str
    confidence: float = Field(default=0.75, ge=0, le=1)
    numeric_fields: NumericFields | None = None


class ExtractedClaims(StrictModel):
    claims: list[ExtractedClaim] = Field(default_factory=list)


class ReportClaim(StrictModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class ReportSection(StrictModel):
    sub_question_id: str
    heading: str
    claims: list[ReportClaim] = Field(default_factory=list)


class ReportDraft(StrictModel):
    summary: str
    key_findings: list[ReportClaim] = Field(default_factory=list)
    detailed_analysis: list[ReportSection] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    unverified_assumptions: list[ReportClaim] = Field(default_factory=list)


class TraceableRow(StrictModel):
    evidence_ids: list[str] = Field(default_factory=list)
    verification_status: Literal["verified", "unverified"] = "verified"

    @model_validator(mode="after")
    def require_unverified_without_evidence(self) -> TraceableRow:
        if not self.evidence_ids and self.verification_status != "unverified":
            raise ValueError("rows without evidence_ids must be marked unverified")
        return self


class MetricRow(TraceableRow):
    entity: str
    metric: str
    normalized_metric: str
    period: str
    scope: str
    value: float
    unit: str
    confidence: float = Field(ge=0, le=1)


class ComparisonTable(StrictModel):
    question: str
    rows: list[MetricRow] = Field(default_factory=list)
    scope_consistent: bool = True
    scope_notes: list[str] = Field(default_factory=list)
    data_as_of: date | None = None


class TimelineEvent(TraceableRow):
    occurred_at: date | None = None
    event: str
    source: str
    thesis_impact: Literal["positive", "negative", "neutral", "uncertain"]


class EventTimeline(StrictModel):
    question: str
    events: list[TimelineEvent] = Field(default_factory=list)
    data_as_of: date | None = None


class RiskItem(TraceableRow):
    risk: str
    likelihood: Literal["low", "medium", "high", "unknown"]
    impact: Literal["low", "medium", "high", "unknown"]
    unverified_prediction: bool = False


class RiskMatrix(StrictModel):
    question: str
    risks: list[RiskItem] = Field(default_factory=list)
    data_as_of: date | None = None


class StructuredResearchOutput(StrictModel):
    comparison_table: ComparisonTable
    event_timeline: EventTimeline
    risk_matrix: RiskMatrix


class RetryTask(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    reason: str
    query: str
    source_type: str = "official"
    sub_question_id: str | None = None
    severity: Literal["low", "medium", "high"] = "medium"
    completed: bool = False


class Issue(StrictModel):
    issue_type: Literal[
        "missing_citation",
        "numeric_conflict",
        "temporal_conflict",
        "outdated_source",
        "missing_counterargument",
        "unverified_projection",
        "injection_risk",
        "contradicts_prior",
        "numeric_inconsistency",
    ]
    severity: Literal["low", "medium", "high"]
    affected_claims: list[str] = Field(default_factory=list)
    message: str
    suggested_retry_task: RetryTask | None = None
    claimed_value: float | None = None
    calculated_value: float | None = None
    formula: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_numeric_inconsistency_audit_fields(self) -> Issue:
        if self.issue_type != "numeric_inconsistency":
            return self
        if (
            self.claimed_value is None
            or self.calculated_value is None
            or not self.formula
            or not self.evidence_ids
        ):
            raise ValueError(
                "numeric_inconsistency requires claimed_value, "
                "calculated_value, formula, and evidence_ids"
            )
        return self


class CriticReport(StrictModel):
    passed: bool
    overall_quality: float = Field(ge=0, le=1)
    issues: list[Issue] = Field(default_factory=list)
    retry_tasks: list[RetryTask] = Field(default_factory=list)
    iteration: int = 0
    forced_pass: bool = False


class TodoItem(StrictModel):
    id: str
    title: str
    status: Literal["pending", "running", "done", "failed"] = "pending"


class EvaluationResult(StrictModel):
    research_id: str
    task_success_rate: float = Field(ge=0, le=1)
    citation_accuracy: float | None = Field(default=None, ge=0, le=1)
    citation_accuracy_reason: str | None = None
    citation_resolution_rate: float = Field(default=0.0, ge=0, le=1)
    bbox_resolution_rate: float | None = Field(default=None, ge=0, le=1)
    bbox_resolution_reason: str | None = None
    citation_repair_retry_rate: float = Field(default=0.0, ge=0, le=1)
    uncited_claim_rate: float = Field(default=0.0, ge=0, le=1)
    critic_catch_rate: float = Field(ge=0, le=1)
    answer_completeness: float | None = Field(
        default=None,
        ge=0,
        le=1,
        exclude_if=lambda value: value is None,
    )
    answer_completeness_reason: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    answer_relevance: float | None = Field(default=None, ge=0, le=1)
    answer_relevance_reason: str | None = None
    answer_shape: float | None = Field(
        default=None,
        ge=0,
        le=1,
        exclude_if=lambda value: value is None,
    )
    answer_shape_reason: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    faithfulness: float | None = Field(default=None, ge=0, le=1)
    faithfulness_reason: str | None = None
    latency_seconds: float = Field(ge=0)
    # Only an LLM ledger may populate usage metrics.  Fixture runs must not
    # manufacture token or currency figures from workflow constants.
    cost_usd: float | None = Field(default=None, ge=0)
    cost_cny: float | None = Field(default=None, ge=0)
    price_source: str | None = None
    token_used: int | None = Field(default=None, ge=0)
    operational_measurement: Literal["llm_ledger", "unavailable"] = "unavailable"
    bad_case_categories: dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class AgentDecision(StrictModel):
    decision_type: str
    made_by: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    criterion: str
    outcome: str
    alternatives_considered: list[str] = Field(default_factory=list)
    iteration: int | None = Field(default=None, ge=0)
    timestamp: datetime = Field(default_factory=utc_now)


class ResearchState(StrictModel):
    research_id: str = Field(default_factory=lambda: str(uuid4()))
    topic: str
    depth_level: int = Field(default=2, ge=1, le=3)
    current_phase: Literal[
        "planning",
        "researching",
        "extracting",
        "critiquing",
        "reporting",
        "evaluating",
        "done",
    ] = "planning"
    status: Literal["running", "paused", "done", "failed", "budget_exceeded"] = "running"
    plan: ResearchPlan | None = None
    todo_list: list[TodoItem] = Field(default_factory=list)
    completed_tasks: list[str] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    search_records: list[SearchRecord] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    evidence_store: list[Evidence] = Field(default_factory=list)
    critic_iteration: int = 0
    retry_queue: list[RetryTask] = Field(default_factory=list)
    critic_report: CriticReport | None = None
    draft_report: str | None = None
    final_report: str | None = None
    report_footnote_evidence: dict[int, str] = Field(default_factory=dict)
    agent_decisions: list[AgentDecision] = Field(default_factory=list)
    structured_output: StructuredResearchOutput | None = None
    evaluation: EvaluationResult | None = None
    token_used: int = 0
    cost_used: float = 0.0
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchRequest(StrictModel):
    topic: str
    depth_level: int = Field(default=2, ge=1, le=3)
    output_format: Literal["markdown"] = "markdown"


class ResearchResponse(StrictModel):
    research_id: str
    status: str
    current_phase: str
    report_url: str | None = None
    metrics: EvaluationResult | None = None
