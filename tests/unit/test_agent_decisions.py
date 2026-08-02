from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from deepresearch_agent.agents import ReporterAgent
from deepresearch_agent.decisions import (
    canonical_decision_json,
    record_agent_decision,
)
from deepresearch_agent.provenance import build_run_manifest, write_run_manifest
from deepresearch_agent.schemas import (
    AgentDecision,
    Evidence,
    ResearchPlan,
    ResearchState,
    SubQuestion,
)
from deepresearch_agent.settings import Settings


class AgentDecisionTests(unittest.TestCase):
    def _decision(self) -> AgentDecision:
        return AgentDecision(
            decision_type="fixture_policy_choice",
            made_by="test_agent",
            inputs={"source_count": 3, "confidence": 0.8},
            criterion="stop when source_count is at least three",
            outcome="stop",
            alternatives_considered=["continue", "mark_insufficient"],
            iteration=1,
            timestamp=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        )

    def test_structure_and_canonical_serialization_are_deterministic(self) -> None:
        decision = self._decision()

        first = canonical_decision_json(decision)
        second = canonical_decision_json(
            AgentDecision.model_validate_json(decision.model_dump_json())
        )

        self.assertEqual(first, second)
        self.assertEqual(
            list(json.loads(first)),
            sorted(json.loads(first)),
        )

    def test_recording_lands_in_trace_manifest_and_reader_visible_report(self) -> None:
        state = ResearchState(
            research_id="decision-run",
            topic="decision visibility",
            plan=ResearchPlan(
                topic="decision visibility",
                depth_level=1,
                sub_questions=[
                    SubQuestion(
                        id="sq",
                        question="What was decided?",
                        search_queries=["decision"],
                    )
                ],
            ),
            evidence_store=[
                Evidence(
                    id="evidence-1",
                    research_id="decision-run",
                    sub_question_id="sq",
                    claim="The decision used three sources.",
                    claim_type="fact",
                    source_url="https://example.com/decision",
                    source_title="Decision source",
                    source_pub_date=date(2026, 7, 23),
                    extract_text="The decision used three sources.",
                )
            ],
        )
        decision = self._decision()
        record_agent_decision(state, decision)

        report = ReporterAgent().report(state)
        settings = Settings(storage_path=Path("unused.db"))
        manifest = build_run_manifest(
            state,
            settings,
            started_at=decision.timestamp,
            ended_at=decision.timestamp,
        )

        self.assertEqual(
            state.metadata["run_trace"]["agent_decisions"],
            [decision.model_dump(mode="json")],
        )
        self.assertEqual(manifest.decision_summary, [decision])
        self.assertNotIn("## Agent 决策记录", report)
        self.assertEqual(state.agent_decisions[0].decision_type, "fixture_policy_choice")
        self.assertEqual(state.agent_decisions[0].inputs["source_count"], 3)

        with tempfile.TemporaryDirectory() as tmp:
            path = write_run_manifest(manifest, Path(tmp))
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["decision_summary"][0]["decision_type"],
            "fixture_policy_choice",
        )


if __name__ == "__main__":
    unittest.main()
