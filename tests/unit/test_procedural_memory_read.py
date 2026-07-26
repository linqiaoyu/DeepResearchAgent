from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from deepresearch_agent.memory import (
    ProceduralMemory,
    ProceduralQuery,
    ProceduralRecord,
    ProceduralSufficiencyResult,
)
from deepresearch_agent.reflection import DeterministicReflectionSignals
from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


class ProceduralMemoryReadTests(unittest.TestCase):
    def test_prior_sufficient_strategy_changes_planning_decision(self) -> None:
        memory = ProceduralMemory()
        memory.write(ProceduralRecord(
            question_type="narrative",
            strategy=("prior authoritative query",),
            sufficiency_result=ProceduralSufficiencyResult(score=0.9, sufficient=True),
            reflection_signals=DeterministicReflectionSignals(), run_id="prior",
            sub_question_id="prior-question", iteration=0,
        ))
        with tempfile.TemporaryDirectory() as tmp:
            engine = DeepResearchEngine(
                settings=Settings(
                    storage_path=Path(tmp) / "research.db",
                    procedural_memory_enabled=True,
                ),
                procedural_memory=memory,
            )
            state = ResearchState(topic="AI Agent 在财富管理行业的落地机会研究")
            engine._planning(state)

        self.assertEqual(state.plan.sub_questions[0].search_queries, ["prior authoritative query"])
        decision = next(item for item in state.agent_decisions if item.decision_type == "procedural_memory_read")
        self.assertEqual(decision.inputs["records_considered"], 1)
        self.assertIn("prior authoritative query", decision.outcome)
        self.assertEqual(memory.query(ProceduralQuery(question_type="narrative")).records[0].run_id, "prior")


if __name__ == "__main__":
    unittest.main()
