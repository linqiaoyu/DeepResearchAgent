"""R109: two dark flags a single-run instrument can never decide.

The Golden Set runner gives every question its own fresh
`case_dir/research.db` (`scripts/run_golden_round.py`), so both memory
capabilities start each question with an empty store. `PROCEDURAL_MEMORY` reads
strategies written by earlier runs and `PRIOR_MEMORY` reads snapshots strictly
older than the run's `as_of`; with nothing to read, each is inert by
construction, not by measurement.

That is the honest verdict for R109's A/B: these two are not "measured and
unhelpful", they are **unmeasurable on this instrument**, and no golden score
may be cited for or against them. Deciding them needs a repeated-question
experiment, which this round did not run.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.memory import EpisodicMemory, ProceduralMemory
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine

TOPIC = "AI Agent 在财富管理行业的落地机会研究"


def _plan_with(**overrides: bool) -> ResearchState:
    with tempfile.TemporaryDirectory() as tmp:
        engine = DeepResearchEngine(
            settings=Settings(
                storage_path=Path(tmp) / "research.db",
                **overrides,
            ),
            procedural_memory=ProceduralMemory(),
            episodic_memory=EpisodicMemory(),
        )
        state = ResearchState(topic=TOPIC)
        engine._planning(state)
    return state


def _component(state: ResearchState, name: str) -> dict:
    activity = state.metadata.get("component_activity", {})
    return activity.get(name, {})


class ProceduralMemoryOnAnEmptyStoreTests(unittest.TestCase):
    def test_enabling_it_changes_no_query_on_a_first_run(self) -> None:
        off = _plan_with(procedural_memory_enabled=False)
        on = _plan_with(procedural_memory_enabled=True)

        self.assertEqual(
            [item.search_queries for item in on.plan.sub_questions],
            [item.search_queries for item in off.plan.sub_questions],
        )

    def test_it_reports_reading_nothing_rather_than_being_skipped(self) -> None:
        """Enabled-and-empty must stay distinguishable from disabled."""
        on = _plan_with(procedural_memory_enabled=True)

        activity = _component(on, "procedural_memory_read")
        self.assertTrue(activity.get("enabled"))
        self.assertEqual(
            [event["outputs"]["strategies_adopted"] for event in activity["events"]],
            [0],
        )

    def test_no_strategy_decision_is_recorded_from_an_empty_store(self) -> None:
        on = _plan_with(procedural_memory_enabled=True)

        self.assertEqual(
            [
                item
                for item in on.agent_decisions
                if item.decision_type == "procedural_memory_read"
            ],
            [],
        )


class PriorMemoryOnAnEmptyStoreTests(unittest.TestCase):
    def test_enabling_it_reads_no_record_on_a_first_run(self) -> None:
        on = _plan_with(prior_memory_enabled=True)

        activity = _component(on, "episodic_memory")
        self.assertTrue(activity.get("enabled"))
        self.assertEqual(
            [event["outputs"]["records_read"] for event in activity["events"]],
            [0],
        )

    def test_it_classifies_no_sub_question_from_a_prior_it_does_not_have(
        self,
    ) -> None:
        off = _plan_with(prior_memory_enabled=False)
        on = _plan_with(prior_memory_enabled=True)

        self.assertEqual(
            on.metadata.get("prior_memory", {}).get("classifications", []),
            [],
        )
        self.assertEqual(
            [item.search_queries for item in on.plan.sub_questions],
            [item.search_queries for item in off.plan.sub_questions],
        )


if __name__ == "__main__":
    unittest.main()
