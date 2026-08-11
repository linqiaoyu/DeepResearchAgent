"""R109: the golden runner must say which fidelity produced its numbers.

The R109 smoke was reported as the product's score before anyone read the run
manifest, which said `FixtureStructuredDataProvider` and `search: replay`.
`run_golden_round.py` hardcoded both. `AGENTS.md` §6 forbids promoting a
content-affecting capability on fixture metrics and §7 forbids calling a mixed
run real, so an A/B between capability flags needs a live arm that exists and
is visible.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from run_golden_round import (  # noqa: E402
    _case_fidelity,
    _evidence_funnel,
    golden_round_environment,
    golden_round_fidelity,
    golden_round_judge_client,
)

from deepresearch_agent.schemas import Evidence, ResearchState, SearchRecord


def _args(**overrides: object) -> SimpleNamespace:
    base = {
        "as_of": "2026-07-01",
        "ledger_path": "ledger.jsonl",
        "run_budget_cny": 3.0,
        "judge_budget_cny": 3.0,
        "recording_dir": "data/recordings/golden_v1",
        "structured_data_provider": "auto",
        "live": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class GoldenRoundFidelityTests(unittest.TestCase):
    def test_the_default_arm_is_replay_and_fixture(self) -> None:
        environment = golden_round_environment(_args())

        self.assertEqual(
            environment["DEEPRESEARCH_STRUCTURED_DATA_PROVIDER"], "fixture"
        )
        self.assertEqual(environment["DEEPRESEARCH_SEARCH_RECORDING_MODE"], "replay")

    def test_the_live_arm_uses_neither_recordings_nor_fixtures(self) -> None:
        environment = golden_round_environment(_args(live=True))

        self.assertEqual(environment["DEEPRESEARCH_STRUCTURED_DATA_PROVIDER"], "auto")
        self.assertEqual(environment["DEEPRESEARCH_SEARCH_RECORDING_MODE"], "off")
        self.assertNotIn("DEEPRESEARCH_SEARCH_RECORDING_DIR", environment)

    def test_the_live_arm_honours_an_explicit_provider(self) -> None:
        environment = golden_round_environment(
            _args(live=True, structured_data_provider="akshare")
        )

        self.assertEqual(
            environment["DEEPRESEARCH_STRUCTURED_DATA_PROVIDER"], "akshare"
        )

    def test_no_arm_leaves_the_provider_unstated(self) -> None:
        """Silence about fidelity is what let a fixture round be read as real."""
        for live in (False, True):
            with self.subTest(live=live):
                environment = golden_round_environment(_args(live=live))

                self.assertIn(
                    "DEEPRESEARCH_STRUCTURED_DATA_PROVIDER", environment
                )
                self.assertIn("DEEPRESEARCH_SEARCH_RECORDING_MODE", environment)

    def test_fidelity_is_structured_for_result_persistence(self) -> None:
        self.assertEqual(
            golden_round_fidelity(_args(live=False)),
            {"llm": "live", "retrieval": "replay", "structured_data": "fixture"},
        )
        self.assertEqual(
            golden_round_fidelity(_args(live=True)),
            {"llm": "live", "retrieval": "live", "structured_data": "live"},
        )

    def test_evidence_funnel_counts_reader_delivery_stages(self) -> None:
        state = ResearchState(topic="funnel")
        state.search_records = [
            SearchRecord(
                query="one",
                source_ids=["source-a", "source-a", "source-b"],
            )
        ]
        state.evidence_store = [
            Evidence(
                id="ev-a",
                research_id=state.research_id,
                sub_question_id="q1",
                claim="A",
                claim_type="fact",
                source_url="https://example.test/a",
                source_title="A",
                extract_text="A",
                confidence=0.9,
            ),
            Evidence(
                id="ev-b",
                research_id=state.research_id,
                sub_question_id="q1",
                claim="B",
                claim_type="fact",
                source_url="https://example.test/b",
                source_title="B",
                extract_text="B",
                confidence=0.9,
            ),
        ]
        state.metadata["context_events"] = [
            {"node": "reporter", "selected_count": 2}
        ]
        state.report_footnote_evidence = {"1": "ev-a", "2": "ev-b"}
        state.final_report = "A is delivered.[^1]\n\n## 参考来源\n[^2]: unused"

        self.assertEqual(
            _evidence_funnel(state),
            {
                "retrieved_sources": 2,
                "extracted_evidence": 2,
                "packed_evidence": 2,
                "cited_evidence": 1,
                "reader_visible_evidence": 1,
            },
        )

    def test_failed_case_still_has_a_zero_funnel(self) -> None:
        self.assertEqual(set(_evidence_funnel(None).values()), {0})

    def test_case_fidelity_uses_actual_provider_metadata(self) -> None:
        state = ResearchState(topic="fidelity")
        state.metadata["provider_fidelity"] = {
            "llm": "real",
            "search": "real",
            "structured_data": "real",
        }
        self.assertEqual(
            _case_fidelity(state, _args(live=True)),
            {"llm": "live", "retrieval": "live", "structured_data": "live"},
        )

    def test_judge_uses_the_shard_ledger_as_its_global_authority(self) -> None:
        judge = golden_round_judge_client(_args(ledger_path="artifacts/shard.jsonl"))

        self.assertEqual(judge.llm_client.ledger_path, Path("artifacts/shard.jsonl"))
        self.assertEqual(
            judge.llm_client.global_ledger_path,
            Path("artifacts/shard.jsonl"),
        )

    def test_live_case_fidelity_fails_closed_when_actual_metadata_is_missing(self) -> None:
        state = ResearchState(topic="fidelity")

        self.assertEqual(
            _case_fidelity(state, _args(live=True)),
            {"llm": "unknown", "retrieval": "unknown", "structured_data": "unknown"},
        )


if __name__ == "__main__":
    unittest.main()
