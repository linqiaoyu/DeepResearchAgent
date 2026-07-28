from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from deepresearch_agent.domains.null import NullDomainPack
from deepresearch_agent.agents import PlannerAgent
from deepresearch_agent.tools import FixtureStructuredDataProvider
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.schemas import Evidence, ResearchPlan, ResearchState, StructuredDataRequest, SubQuestion
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine
from deepresearch_agent.workflow.nodes.research import ResearchOneDependencies
from deepresearch_agent.orchestration import RunScope, SearchQuota
from deepresearch_agent.tools import RunToolContext


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
    def test_research_one_runtime_has_explicit_dependencies_and_rejects_missing_ones(self) -> None:
        with self.assertRaisesRegex(ValueError, "researcher"):
            ResearchOneDependencies(
                settings=object(),
                capability_selector=object(),
                researcher=None,
                state_loader=lambda _state: None,
                branch_budget_enabled=lambda: False,
            )

        class Researcher:
            def structured_evidence(self, *_args: object) -> tuple[list[object], dict[str, int], list[object]]:
                return [], {"requests": 0}, []

            def research(self, *_args: object, **_kwargs: object) -> tuple[list[object], list[object]]:
                return [], []

            def research_with_budget(self, *_args: object, **_kwargs: object) -> tuple[list[object], list[object], int, bool, list[object]]:
                return [], [], 0, False, []

        state = ResearchState(topic="explicit node")
        sub_question = SubQuestion(id="one", question="q", search_queries=[])
        dependencies = ResearchOneDependencies(
            settings=SimpleNamespace(
                dynamic_capability_enabled=False,
                prior_memory_enabled=False,
            ),
            capability_selector=object(),
            researcher=Researcher(),
            state_loader=lambda _state: state,
            branch_budget_enabled=lambda: False,
        )
        from deepresearch_agent.workflow.nodes.research import ResearchOneNode

        result = ResearchOneNode(dependencies).run(
            {"fanout_sub_question": sub_question.model_dump(mode="json")},
            run_scope=RunScope(RunToolContext.for_run(), SearchQuota(1)),
        )
        self.assertEqual(result["research_sources"], {"one": []})
        self.assertFalse(hasattr(dependencies, "engine"))

    def test_consumers_accept_only_their_required_capability_protocol(self) -> None:
        class PlanningOnly:
            def deterministic_plan(self, _topic: str, _depth_level: int) -> None:
                return None

            def propagate_plan_identity(self, plan: ResearchPlan, _topic: str) -> ResearchPlan:
                return plan

            def valid_structured_request(self, _request: StructuredDataRequest) -> bool:
                return False

        class FixtureAliasesOnly:
            def fixture_metric_aliases(self) -> dict[str, str]:
                return {}

        planner = PlannerAgent(domain_pack=PlanningOnly())
        provider = FixtureStructuredDataProvider(domain_pack=FixtureAliasesOnly())

        self.assertEqual(planner.plan("generic", depth_level=1).topic, "generic")
        self.assertIsNotNone(provider)

    def test_graph_skill_selection_uses_the_injected_pack_capability(self) -> None:
        graph_assembly = (
            Path(__file__).parents[2]
            / "src/deepresearch_agent/workflow/graph_assembly.py"
        ).read_text(encoding="utf-8")

        self.assertIn("is_applicable=self.domain_pack.metric_skill_applicable", graph_assembly)
        self.assertNotIn("finance_metric_skill_applicable", graph_assembly)

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
                self.assertIs(engine.evaluator.domain_pack, pack)
                self.assertIsInstance(engine.reporter.grounded_fact_renderer, _NeutralRenderer)
            finally:
                engine.close()

    def test_null_pack_runs_a_complete_offline_workflow_without_finance_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    structured_logging_enabled=False,
                ),
                domain_pack=NullDomainPack(),
            )
            try:
                state = engine.run("warehouse robotics", depth_level=1)
            finally:
                engine.close()

        self.assertEqual(state.status, "done")
        self.assertFalse(
            any(question.structured_data_requests for question in state.plan.sub_questions)
        )
        self.assertFalse(any(source.url.startswith("cninfo") for source in state.sources))
        self.assertNotIn("主营业务毛利率", state.final_report or "")

    def test_registry_rejects_an_uninstalled_pack(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown domain pack"):
            load_domain_pack("uninstalled")


if __name__ == "__main__":
    unittest.main()
