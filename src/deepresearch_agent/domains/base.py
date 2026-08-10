"""Neutral defaults for every capability a domain may be asked for.

R111: the `DomainPack` protocol declares 51 methods, so writing a second domain
meant writing 51 of them -- an extension point nobody can afford to use. This
module answers all of them with "this domain has no opinion", so a real domain
subclasses it and overrides only what it actually decides.

Every default is inert on purpose: no metric vocabulary, no disclosure policy,
no numeric interpretation, no skills. A domain that forgets to override
something gets nothing -- never another domain's answer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from deepresearch_agent.decisions import record_agent_decision
from deepresearch_agent.domains.protocols import NumericCitationPolicy, RetrievalFilterValues
from deepresearch_agent.reporting.grounded_facts import GroundedFactBatch
from deepresearch_agent.schemas import AgentDecision


@dataclass(frozen=True)
class _NullRenderer:
    def render(self, _state: Any) -> GroundedFactBatch:
        return GroundedFactBatch(required_labels=(), claims=(), gaps=())

    def is_supported(self, _text: str, _evidence: list[Any], _state: Any, *, labels: set[str]) -> bool:
        return not labels


@dataclass(frozen=True)
class _NullTableExtractors:
    def authoritative_backfills(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []

    def merge_authoritative_evidence(self, evidence: list[Any], _backfills: list[Any]) -> list[Any]:
        return evidence


@dataclass(frozen=True)
class _NullNumericChecker:
    def check(self, state: Any) -> list[Any]:
        # Numeric checking is enabled by default.  The capability-empty pack
        # still records the explicit no-op so the Critic's decision contract
        # remains truthful without inventing finance-specific relationships.
        record_agent_decision(
            state,
            AgentDecision(
                decision_type="numeric_consistency_scan",
                made_by="NullDomainPack",
                inputs={"numeric_observation_count": 0, "check_count": 0},
                criterion="no domain numeric relationships are available",
                outcome="no_applicable_relationships",
                alternatives_considered=["run_applicable_checks"],
            ),
        )
        return []


@dataclass(frozen=True)
class _NullCitationPolicy:
    # R112: parameter names and types must match `NumericCitationPolicy`
    # exactly. They did not -- the names carried leading underscores and
    # `cited_evidence` was declared `list[Any]` against a protocol that promises
    # `Sequence[Any]` -- so the null pack was not actually substitutable for the
    # protocol it claimed to satisfy. Nothing caught it because no type checker
    # ran here.
    def has_numeric_mismatch(
        self,
        claim_text: str,
        cited_evidence: Sequence[Any],
        *,
        required_metrics: set[str] | None = None,
    ) -> bool:
        del claim_text, cited_evidence
        return bool(required_metrics)

    def is_main_business_margin_dimension(self, dimension: str | None) -> bool:
        del dimension
        return False


class BaseDomainPack:
    """Neutral implementations of every capability the harness may ask for.

    R111: the `DomainPack` protocol declares 51 methods, so writing a second
    domain meant writing 51 -- which is not an extension point, it is a
    rewrite. Subclass this and override only what the domain actually
    decides; everything else answers "this domain has no opinion", which is
    what made the null pack able to run a complete workflow in the first
    place.

    Every default here is inert on purpose: no metric vocabulary, no
    disclosure policy, no numeric interpretation, no skills. A domain that
    forgets to override something gets nothing, never a finance answer.
    """

    name = "base"

    def canonical_metric(self, value: str | None) -> str:
        return (value or "").strip()

    def parse_period(self, _value: str | None) -> str | None:
        return None

    def amount_units(self) -> Mapping[str, Decimal]:
        return {}

    def structured_metric_aliases(self) -> Mapping[str, str]:
        return {}

    def fixture_metric_aliases(self) -> Mapping[str, str]:
        return {}

    def default_structured_metrics(self) -> tuple[str, ...]:
        return ()

    def structured_metric_unit(self, _metric_name: str) -> str | None:
        return None

    def equity_listing_sources(self) -> tuple[tuple[str, str, str], ...]:
        return ()

    def equity_exchange_label(self) -> str:
        return "unknown"

    def structured_issuer_aliases(self) -> Mapping[str, str]:
        return {}

    def structured_xbrl_concepts(self) -> Mapping[str, tuple[str, ...]]:
        return {}

    def unsupported_xbrl_metrics(self) -> tuple[str, ...]:
        return ()

    def financial_intent_terms(self) -> tuple[str, ...]:
        return ()

    def primary_source_keyword(self, *, financial_intent: bool) -> str:
        return "notice" if financial_intent else "source"

    def primary_source_terms(self, *, financial_intent: bool) -> tuple[str, ...]:
        return ()

    def grounded_fact_renderer(self) -> _NullRenderer:
        return _NullRenderer()

    def table_extractors(self) -> _NullTableExtractors:
        return _NullTableExtractors()

    def metric_table_path(self) -> Path:
        return Path(__file__).resolve().parents[3] / "data/mock_data/null_metric_table.json"

    def metric_claim_pattern(self) -> re.Pattern[str]:
        return re.compile(r"(?!)")

    def comparison_observed(self, _evidence: Any) -> bool:
        return False

    def is_historical_annual_disclosure(self, _evidence: Any) -> bool:
        return False

    def is_legal_disclaimer_template(self, _evidence: Any) -> bool:
        return False

    def reader_risk_visible(self, _line: str) -> bool:
        return True

    def reader_assumption_visible(self, _line: str) -> bool:
        return True

    def reader_metric_gap_explanation(
        self, _metric: str, derived_periods: Sequence[str] = ()
    ) -> str:
        if derived_periods:
            return (
                "Not disclosed directly; derived from its components for "
                f"{', '.join(derived_periods)} -- see the derived metrics section."
            )
        return "No citable source fact was obtained; consult the primary disclosure."

    def derived_metric_periods(self, _evidence: list[Any]) -> Mapping[str, tuple[str, ...]]:
        return {}

    def metrics_mentioned(self, _text: str, _required: set[str]) -> set[str]:
        # A domain with no metric vocabulary cannot say what a sentence is
        # about, so it claims nothing and the evidence-sharing rule decides.
        return set()

    def evidence_matches_metric(self, _evidence: Any, _required_metric: str) -> bool:
        return False

    def demo_numeric_claim(self, _claims: list[Any]) -> None:
        return None

    def demo_scope_claim(self, _claims: list[Any], _numeric_change: Any | None) -> None:
        return None

    def scope_change_summary(self, label: str) -> str:
        return label

    def is_full_annual_report_query(self, _keyword: str) -> bool:
        return False

    def is_full_annual_report_title(self, _title: str) -> bool:
        return False

    def report_year_from_title(self, _title: str) -> int | None:
        return None

    def is_amount_unit(self, _value: str) -> bool:
        return False

    def golden_type_distribution(self) -> Mapping[str, int]:
        return {}

    def evidence_explains_change(self, _text: str) -> bool:
        return False

    def document_type_tokens(self) -> tuple[str, ...]:
        return ()

    def document_type_for_direction(self, _direction: str) -> str:
        return "source"

    def metric_gap_direction(self) -> str:
        return "gather source evidence"

    def evidence_gap_direction(self) -> str:
        return "gather independent evidence"

    def metric_skill_applicable(self, _metadata: Any, _context: str) -> bool:
        return False

    def numeric_consistency_checker(self, _metric_table: dict[str, Any], *, relative_tolerance: float, absolute_tolerance: float) -> _NullNumericChecker:
        del relative_tolerance, absolute_tolerance
        return _NullNumericChecker()

    def numeric_citation_policy(self) -> NumericCitationPolicy:
        return _NullCitationPolicy()

    def deterministic_plan(self, _topic: str, _depth_level: int) -> None:
        return None

    def propagate_plan_identity(self, plan: Any, _topic: str) -> Any:
        return plan

    def valid_structured_request(self, _request: Any) -> bool:
        return False

    def retrieval_filter_values(self, _query: str) -> RetrievalFilterValues:
        return RetrievalFilterValues()

    def expand_retrieval_query(self, query: str) -> str:
        return query

    def web_source_rejection_reason(
        self,
        _source: Any,
        _target_periods: tuple[str, ...],
    ) -> None:
        return None
