from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.schemas import (
    ResearchState,
    StructuredDataRequest,
    SubQuestion,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.tools import (
    DeterministicCapabilitySelector,
    FixtureSearchTool,
    FixtureStructuredDataProvider,
    build_capability_registry,
)
from deepresearch_agent.workflow import DeepResearchEngine


def _registry():
    return build_capability_registry(
        search_provider=FixtureSearchTool(),
        structured_data_provider=FixtureStructuredDataProvider(),
    )


class DynamicCapabilitySelectionTest(unittest.TestCase):
    def test_financial_and_narrative_types_select_from_registry(self) -> None:
        state = ResearchState(topic="能力选择")
        selector = DeterministicCapabilitySelector(_registry())
        financial = SubQuestion(
            id="revenue",
            question="核验营收",
            search_queries=["营收"],
            structured_data_requests=[
                StructuredDataRequest(
                    capability="financial_indicators",
                    symbol="300750",
                )
            ],
        )
        narrative = SubQuestion(
            id="strategy",
            question="分析竞争战略",
            search_queries=["竞争战略"],
        )

        financial_selection = selector.select(state, financial)
        narrative_selection = selector.select(state, narrative)

        self.assertEqual(
            financial_selection.sub_question_type,
            "financial_metric",
        )
        self.assertEqual(
            financial_selection.selected_capabilities,
            ("structured_data_provider", "web_fetch", "web_search"),
        )
        self.assertEqual(
            financial_selection.rejected_capabilities,
            (),
        )
        self.assertEqual(
            narrative_selection.selected_capabilities,
            ("web_search",),
        )
        self.assertEqual(
            narrative_selection.rejected_capabilities,
            ("structured_data_provider", "web_fetch"),
        )

    def test_financial_and_event_verification_select_fetch_with_reason(
        self,
    ) -> None:
        state = ResearchState(topic="一手来源核验")
        selector = DeterministicCapabilitySelector(_registry())
        financial = SubQuestion(
            id="finance",
            question="核验年度营业收入",
            search_queries=["年度报告"],
            structured_data_requests=[
                StructuredDataRequest(
                    capability="financial_indicators",
                    symbol="300750",
                )
            ],
        )
        event = SubQuestion(
            id="event",
            question="梳理项目公告、开工与投产时间线",
            search_queries=["项目公告"],
        )

        selections = [
            selector.select(state, financial),
            selector.select(state, event),
        ]

        self.assertTrue(
            all(
                "web_fetch" in item.selected_capabilities
                for item in selections
            )
        )
        self.assertTrue(all(item.criterion for item in selections))
        self.assertTrue(
            all(
                "first-party disclosure" in item.criterion
                for item in selections
            )
        )

    def test_no_matching_rule_explicitly_falls_back_to_fixed_set(self) -> None:
        state = ResearchState(topic="回退")
        selector = DeterministicCapabilitySelector(_registry(), rules={})
        sub_question = SubQuestion(
            id="narrative",
            question="叙事研究",
            search_queries=["叙事"],
        )

        selection = selector.select(state, sub_question)

        self.assertTrue(selection.fallback)
        self.assertEqual(
            selection.selected_capabilities,
            (
                "web_search",
                "web_fetch",
                "structured_data_provider",
            ),
        )
        decision = state.agent_decisions[-1]
        self.assertTrue(decision.inputs["fallback"])
        self.assertIn("fall back", decision.criterion)
        self.assertEqual(
            decision.inputs["candidate_capabilities"],
            ["structured_data_provider", "web_fetch", "web_search"],
        )

    def test_selection_decision_records_candidates_winner_and_losers(
        self,
    ) -> None:
        state = ResearchState(topic="可见决策")
        selector = DeterministicCapabilitySelector(_registry())

        selector.select(
            state,
            SubQuestion(
                id="story",
                question="行业叙事",
                search_queries=["行业"],
            ),
        )

        decision = state.agent_decisions[-1]
        self.assertEqual(decision.decision_type, "capability_selection")
        self.assertEqual(
            decision.inputs["sub_question_type"],
            "narrative",
        )
        self.assertEqual(
            decision.inputs["selected_capabilities"],
            ["web_search"],
        )
        self.assertEqual(
            decision.inputs["rejected_capabilities"],
            ["structured_data_provider", "web_fetch"],
        )

    def test_enabled_engine_uses_selection_and_passes_decision_gate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = Settings(
                storage_path=Path(temp_dir) / "research.db",
                runs_root=Path(temp_dir) / "runs",
                run_manifest_enabled=False,
                structured_logging_enabled=False,
                max_critic_iter=1,
                dynamic_capability_enabled=True,
            )
            engine = DeepResearchEngine(settings=settings)
            state = engine.run(
                topic="AI Agent 在财富管理行业的落地机会研究",
                depth_level=1,
            )
            engine._checkpoint_conn.close()

        selections = state.metadata["capability_selections"]
        self.assertEqual(len(selections), 3)
        self.assertTrue(
            all(
                item["selected_capabilities"] == ["web_search"]
                for item in selections.values()
            )
        )
        decisions = [
            item
            for item in state.agent_decisions
            if item.decision_type == "capability_selection"
        ]
        self.assertEqual(len(decisions), 3)
        self.assertIn("capability_selection", state.final_report or "")

    def test_switch_off_keeps_fixed_researcher_tools(self) -> None:
        settings = Settings(storage_path=Path("test.db"))
        self.assertFalse(settings.dynamic_capability_enabled)


if __name__ == "__main__":
    unittest.main()
