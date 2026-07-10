from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


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


class Source(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    url: str
    source_type: str
    published_at: date
    content: str
    credibility: float = Field(default=0.8, ge=0, le=1)


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
    value: float
    unit: str
    data_source: str
    as_of: date


class NumericFields(StrictModel):
    entity: str | None = None
    metric_name: str | None = None
    period: str | None = None
    dimension: str = "未标注"
    value: float | None = None
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
    source_pub_date: date
    extract_text: str
    extract_offset_start: int = 0
    confidence: float = Field(default=0.75, ge=0, le=1)
    structured_record: StructuredDataRecord | None = None
    numeric_fields: NumericFields | None = None
    numeric_fields_incomplete: bool = False
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
    ]
    severity: Literal["low", "medium", "high"]
    affected_claims: list[str] = Field(default_factory=list)
    message: str
    suggested_retry_task: RetryTask | None = None


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
    citation_repair_retry_rate: float = Field(default=0.0, ge=0, le=1)
    uncited_claim_rate: float = Field(default=0.0, ge=0, le=1)
    critic_catch_rate: float = Field(ge=0, le=1)
    answer_relevance: float | None = Field(default=None, ge=0, le=1)
    answer_relevance_reason: str | None = None
    faithfulness: float | None = Field(default=None, ge=0, le=1)
    faithfulness_reason: str | None = None
    latency_seconds: float = Field(ge=0)
    cost_usd: float = Field(ge=0)
    cost_cny: float | None = Field(default=None, ge=0)
    price_source: str | None = None
    token_used: int = Field(ge=0)
    bad_case_categories: dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


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
