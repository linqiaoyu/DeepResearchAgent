"""R109: the only capability flag no test ever turned on.

`LLM_TOOL_SELECTION_ENABLED` had three source references and zero tests
constructing it enabled, so its behaviour when on was unknown rather than good.
Turning it on exposed a hazard: `_research_one_node` sets a sub-question's
capabilities to exactly what the selection carries whenever
`dynamic_capability_enabled` is true, which is the default. A model returning
no tool call therefore left the branch with no web_search, no
structured_data_provider and no web_fetch -- it researched nothing and reported
nothing wrong.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from deepresearch_agent.schemas import ResearchState, SubQuestion
from deepresearch_agent.tools.capability_registry import build_capability_registry
from deepresearch_agent.tools.capability_selector import (
    DeterministicCapabilitySelector,
    LLMCapabilitySelector,
)


@dataclass
class _Result:
    """The provider's shape: tool calls are dicts, not objects."""

    tool_calls: list[dict[str, Any]]


class _StubClient:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.calls = 0

    def complete_with_tools(self, **kwargs: Any) -> _Result:
        self.calls += 1
        return _Result(
            tool_calls=[{"function": {"name": name}} for name in self.names]
        )


class LLMCapabilitySelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = build_capability_registry(
            search_provider=object(),
            structured_data_provider=object(),
        )
        self.state = ResearchState(topic="贵州茅台 2024 年营业收入")
        self.sub_question = SubQuestion(
            id="q1",
            question="贵州茅台 2024 年营业收入是多少？",
            search_queries=["600519 年报"],
        )
        self.deterministic = DeterministicCapabilitySelector(self.registry).select(
            self.state, self.sub_question
        )

    def test_a_registered_choice_is_used(self) -> None:
        chosen = self.deterministic.selected_capabilities[0]
        selector = LLMCapabilitySelector(self.registry, _StubClient([chosen]))

        selection = selector.select(self.state, self.sub_question)

        self.assertIn(chosen, selection.selected_capabilities)
        self.assertFalse(selection.fallback)

    def test_an_unregistered_choice_is_rejected_and_recorded(self) -> None:
        chosen = self.deterministic.selected_capabilities[0]
        selector = LLMCapabilitySelector(
            self.registry, _StubClient([chosen, "wire_transfer"])
        )

        selection = selector.select(self.state, self.sub_question)

        self.assertNotIn("wire_transfer", selection.selected_capabilities)
        self.assertIn("wire_transfer", selection.rejected_capabilities)
        reasons = {
            event.get("reason")
            for event in self.state.metadata.get("degradation_events", [])
        }
        self.assertIn("unknown_capability", reasons)

    def test_selecting_nothing_falls_back_instead_of_researching_nothing(
        self,
    ) -> None:
        selector = LLMCapabilitySelector(self.registry, _StubClient([]))

        selection = selector.select(self.state, self.sub_question)

        self.assertTrue(selection.selected_capabilities)
        self.assertEqual(
            selection.selected_capabilities,
            self.deterministic.selected_capabilities,
        )
        self.assertTrue(selection.fallback)

    def test_the_fallback_is_reported_to_the_run(self) -> None:
        selector = LLMCapabilitySelector(self.registry, _StubClient([]))

        selector.select(self.state, self.sub_question)

        reasons = {
            event.get("reason")
            for event in self.state.metadata.get("degradation_events", [])
        }
        self.assertIn("empty_selection", reasons)

    def test_every_unregistered_choice_still_leaves_a_usable_selection(self) -> None:
        """Unknown-only output is empty output once the unknowns are dropped."""
        selector = LLMCapabilitySelector(self.registry, _StubClient(["wire_transfer"]))

        selection = selector.select(self.state, self.sub_question)

        self.assertTrue(selection.selected_capabilities)
        self.assertTrue(selection.fallback)


if __name__ == "__main__":
    unittest.main()
