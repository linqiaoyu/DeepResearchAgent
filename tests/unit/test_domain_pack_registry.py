from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.schemas import Evidence, ResearchPlan, ResearchState, StructuredDataRequest
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


class _NeutralRenderer:
    def render(self, _state: ResearchState) -> object:
        raise AssertionError("renderer must not run during engine construction")

    def is_supported(
        self,
        _text: str,
        _evidence: list[Evidence],
        _state: ResearchState,
        *,
        labels: set[str],
    ) -> bool:
        del labels
        return True


class _NeutralTableExtractors:
    def authoritative_backfills(self, *_args: object, **_kwargs: object) -> list[object]:
        return []

    def merge_authoritative_evidence(
        self, evidence: list[object], _backfills: list[object]
    ) -> list[object]:
        return evidence


class _NeutralNumericCitationPolicy:
    def has_numeric_mismatch(self, *_args: object, **_kwargs: object) -> bool:
        return False

    def is_main_business_margin_dimension(self, _dimension: str | None) -> bool:
        return False


class _NeutralPack:
    name = "neutral"

    def canonical_metric(self, value: str | None) -> str:
        return (value or "").strip()

    def parse_period(self, value: str | None) -> str | None:
        return value

    def amount_units(self) -> dict[str, Decimal]:
        return {"unit": Decimal("1")}

    def primary_source_keyword(self, *, financial_intent: bool) -> str:
        return "primary" if financial_intent else "notice"

    def primary_source_terms(self, *, financial_intent: bool) -> tuple[str, ...]:
        return ("primary-term",) if financial_intent else ()

    def grounded_fact_renderer(self) -> _NeutralRenderer:
        return _NeutralRenderer()

    def table_extractors(self) -> _NeutralTableExtractors:
        return _NeutralTableExtractors()

    def metric_table_path(self) -> Path:
        return (
            Path(__file__).parents[2]
            / "skills/finance-metric-normalization/resources/finance_metric_normalization.json"
        )

    def metric_skill_applicable(self, _metadata: object, _context: str) -> bool:
        return False

    def numeric_consistency_checker(self, *_args: object, **_kwargs: object) -> object:
        return object()

    def numeric_citation_policy(self) -> _NeutralNumericCitationPolicy:
        return _NeutralNumericCitationPolicy()

    def deterministic_plan(self, _topic: str, _depth_level: int) -> None:
        return None

    def propagate_plan_identity(self, plan: ResearchPlan, _topic: str) -> ResearchPlan:
        return plan

    def valid_structured_request(self, _request: StructuredDataRequest) -> bool:
        return False


class DomainPackRegistryTests(unittest.TestCase):
    def test_engine_composes_an_injected_pack_without_finance_default(self) -> None:
        pack = _NeutralPack()
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    structured_logging_enabled=False,
                ),
                domain_pack=pack,
            )
            try:
                self.assertIs(engine.domain_pack, pack)
                self.assertIs(engine.researcher.domain_pack, pack)
                self.assertIs(engine.planner.domain_pack, pack)
                self.assertIsInstance(
                    engine.reporter.numeric_citation_policy,
                    _NeutralNumericCitationPolicy,
                )
                self.assertIsInstance(
                    engine.evaluator.numeric_citation_policy,
                    _NeutralNumericCitationPolicy,
                )
                self.assertIsInstance(engine.reporter.grounded_fact_renderer, _NeutralRenderer)
            finally:
                engine.close()

    def test_registry_rejects_an_uninstalled_pack(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown domain pack"):
            load_domain_pack("uninstalled")


if __name__ == "__main__":
    unittest.main()
