from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import re
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


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


class RetrievalReference(StrictModel):
    chunk_id: str
    document_version_id: str
    index_version: str
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_span(self) -> RetrievalReference:
        if self.char_end <= self.char_start:
            raise ValueError("retrieval reference char_end must exceed char_start")
        return self


class Source(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    url: str
    source_type: str
    published_at: date | None = None
    # RAG corpus metadata stores a reporting-period end, not a disclosure date.
    # Keep the two concepts separate so as-of evidence never invents a filing date.
    report_period_end: date | None = None
    source_date_unknown_reason: str | None = None
    content: str
    credibility: float = Field(default=0.8, ge=0, le=1)
    source_tier: Literal["primary", "secondary", "unknown"] = Field(
        default="unknown",
        exclude_if=lambda value: value == "unknown",
    )
    content_truncated: bool = Field(default=False, exclude_if=lambda value: not value)
    bbox_index: list[TextBoundingBox] = Field(default_factory=list)
    table_index: list[list[list[str | None]]] = Field(default_factory=list)
    retrieval_ref: RetrievalReference | None = None


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
    # Retrieval time is operational provenance only. It must never be rendered
    # as the publication date of the underlying financial observation.
    as_of: date
    # ``None`` explicitly means that the provider cannot establish a source
    # publication date. Older recorded trajectories deserialize to this state
    # and downstream readers must render the resulting uncertainty.
    source_pub_date: date | None = None
    # A provider-origin URL keeps structured facts independently auditable.
    # Legacy fixtures predate this field and intentionally fall back to their
    # provider-specific synthetic URI in ResearcherAgent.
    source_url: str | None = None


#: Declared here rather than beside the extractor's other bounds because
#: `NumericFields` is defined first; see the R098 note on `MAX_EXTRACTED_CLAIMS`.
MAX_NUMERIC_FIELD_CHARS = 32


class NumericFields(StrictModel):
    entity: str | None = Field(default=None, max_length=MAX_NUMERIC_FIELD_CHARS)
    metric_name: str | None = Field(default=None, max_length=MAX_NUMERIC_FIELD_CHARS)
    period: str | None = Field(default=None, max_length=MAX_NUMERIC_FIELD_CHARS)
    dimension: str = Field(default="未标注", max_length=MAX_NUMERIC_FIELD_CHARS)
    # This mirror is consumed by numeric guards, so it must preserve the same
    # source value as StructuredDataRecord rather than reintroduce float loss.
    # `Decimal` renders as a JSON string, and its own schema declares no
    # textual bound, so the field declares one for the provider to read.
    value: Decimal | None = Field(
        default=None, json_schema_extra={"maxLength": MAX_NUMERIC_FIELD_CHARS}
    )
    unit: str | None = Field(default=None, max_length=MAX_NUMERIC_FIELD_CHARS)

    @model_validator(mode="after")
    def normalize_unit_misfiled_as_dimension(self) -> NumericFields:
        """Keep amount units out of the scope field used for comparisons.

        Older extraction payloads sometimes placed a table's magnitude header
        in both fields.  It describes magnitude, not period/entity scope, and
        therefore must not create a synthetic scope conflict downstream.
        """
        dimension = self.dimension.strip()
        if re.fullmatch(r"[一二三四五六七八九十百千万亿]*元", dimension):
            if self.unit is None:
                self.unit = dimension
            self.dimension = "未标注"
        return self

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
    report_period_end: date | None = None
    source_date_unknown_reason: str | None = None
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
    retrieval_ref: RetrievalReference | None = None
    injection_risk_score: float = Field(default=0.0, ge=0, le=1)
    injection_patterns: list[str] = Field(default_factory=list)
    extracted_at: datetime = Field(default_factory=utc_now)


#: R092: the extractor's response size is bounded by the schema, not by asking.
#: R091 measured it emitting the full 4096 and then the full 8192 completion
#: tokens with `finish_reason=length` while `prompts/extractor.md` asked for at
#: most 24 claims -- an unbounded schema states no limit to the model and
#: enforces none on the way back. These bounds travel to the provider inside
#: `model_json_schema()` and are checked by validation, and
#: `scripts/check_llm_agent_liveness.py` asserts the worst case they permit
#: still fits the role's completion cap.
#:
#: R098: R092 bounded two of this schema's fields and left `claim`,
#: `source_url` and every `NumericFields` string with no `maxLength`, so the
#: worst case it permits was never finite -- the R097 live run truncated three
#: of eleven extractor batches at 8192 tokens and lost two of them whole. A
#: field left unbounded here is a field the provider is told nothing about.
MAX_EXTRACTED_CLAIMS = 8
MAX_EXTRACT_TEXT_CHARS = 300
MAX_EXTRACT_CLAIM_CHARS = 160
MAX_SOURCE_URL_CHARS = 256


class ExtractedClaim(StrictModel):
    claim: str = Field(max_length=MAX_EXTRACT_CLAIM_CHARS)
    claim_type: Literal["fact", "opinion", "data", "projection"]
    source_url: str = Field(max_length=MAX_SOURCE_URL_CHARS)
    extract_text: str = Field(max_length=MAX_EXTRACT_TEXT_CHARS)
    confidence: float = Field(default=0.75, ge=0, le=1)
    numeric_fields: NumericFields | None = None


class ExtractedClaims(StrictModel):
    claims: list[ExtractedClaim] = Field(
        default_factory=list, max_length=MAX_EXTRACTED_CLAIMS
    )


#: R098: `ReportDraft` reached production with no `maxLength` and no `maxItems`
#: on any field, so the JSON Schema the reporter receives stated no limit
#: anywhere. The R097 live run emitted 8192 completion tokens with
#: `finish_reason=length`, the salvage found no complete element before the cut,
#: and the reporter fell back -- delivering a 22-line report with zero authored
#: analysis lines and zero cited numbers. R092 had already learned this on the
#: extractor and the lesson was never carried across to the second role.
#:
#: The list bounds match what `ReporterAgent._render_llm_report` actually
#: renders (6 key findings, 3 claims per section, 6 risks), so a response that
#: respects them loses nothing to the renderer.
MAX_REPORT_SUMMARY_CHARS = 320
MAX_REPORT_CLAIM_CHARS = 140
MAX_REPORT_HEADING_CHARS = 60
MAX_REPORT_SUB_QUESTION_ID_CHARS = 64
MAX_REPORT_EVIDENCE_ID_CHARS = 40
MAX_REPORT_CLAIM_EVIDENCE_IDS = 3
MAX_REPORT_SECTION_CLAIMS = 3
MAX_REPORT_SECTIONS = 4
MAX_REPORT_RISKS = 6
MAX_REPORT_RISK_CHARS = 140
MAX_REPORT_ASSUMPTIONS = 3
MAX_REPORT_KEY_FINDINGS = 6


class ReportClaim(StrictModel):
    text: str = Field(max_length=MAX_REPORT_CLAIM_CHARS)
    evidence_ids: list[
        Annotated[str, StringConstraints(max_length=MAX_REPORT_EVIDENCE_ID_CHARS)]
    ] = Field(default_factory=list, max_length=MAX_REPORT_CLAIM_EVIDENCE_IDS)


class ReportSection(StrictModel):
    sub_question_id: str = Field(max_length=MAX_REPORT_SUB_QUESTION_ID_CHARS)
    heading: str = Field(max_length=MAX_REPORT_HEADING_CHARS)
    claims: list[ReportClaim] = Field(
        default_factory=list, max_length=MAX_REPORT_SECTION_CLAIMS
    )


class ReportDraft(StrictModel):
    """Ordered by what survives to the reader, because a cut keeps a prefix.

    R095: `ReporterAgent._enforce_reader_fidelity` always replaces the rendered
    `关键发现` with mechanically grounded facts when the domain requests
    metrics, so `key_findings` is the one field the reader never receives as
    written. It used to be emitted second, ahead of the analysis, and R094's
    truncated report lost `detailed_analysis` and `unverified_assumptions`
    entirely -- the reader got zero authored lines while the discarded section
    had consumed the budget. Emitting it last means a truncation costs the
    section that is discarded anyway.
    """

    summary: str = Field(max_length=MAX_REPORT_SUMMARY_CHARS)
    detailed_analysis: list[ReportSection] = Field(
        default_factory=list, max_length=MAX_REPORT_SECTIONS
    )
    risks: list[
        Annotated[str, StringConstraints(max_length=MAX_REPORT_RISK_CHARS)]
    ] = Field(default_factory=list, max_length=MAX_REPORT_RISKS)
    unverified_assumptions: list[ReportClaim] = Field(
        default_factory=list, max_length=MAX_REPORT_ASSUMPTIONS
    )
    key_findings: list[ReportClaim] = Field(
        default_factory=list, max_length=MAX_REPORT_KEY_FINDINGS
    )


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
    lexical_overlap: float | None = Field(default=None, ge=0, le=1)
    semantic_relevance: float | None = Field(default=None, ge=0, le=1)
    semantic_relevance_reason: str | None = None
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
    citation_density: float = Field(default=0.0, ge=0, le=1)
    semantic_faithfulness: float | None = Field(default=None, ge=0, le=1)
    semantic_faithfulness_reason: str | None = None
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
