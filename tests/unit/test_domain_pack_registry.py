from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.schemas import Evidence, ResearchState
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

    def grounded_fact_renderer(self) -> _NeutralRenderer:
        return _NeutralRenderer()

    def table_extractors(self) -> _NeutralTableExtractors:
        return _NeutralTableExtractors()

    def metric_table_path(self) -> Path:
        return (
            Path(__file__).parents[2]
            / "skills/finance-metric-normalization/resources/finance_metric_normalization.json"
        )

    def numeric_consistency_checker(self, *_args: object, **_kwargs: object) -> object:
        return object()


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
                self.assertIsInstance(engine.reporter.grounded_fact_renderer, _NeutralRenderer)
            finally:
                engine.close()

    def test_registry_rejects_an_uninstalled_pack(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown domain pack"):
            load_domain_pack("uninstalled")


if __name__ == "__main__":
    unittest.main()
