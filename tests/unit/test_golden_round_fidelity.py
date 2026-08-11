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

from run_golden_round import golden_round_environment, golden_round_fidelity  # noqa: E402


def _args(**overrides: object) -> SimpleNamespace:
    base = {
        "as_of": "2026-07-01",
        "ledger_path": "ledger.jsonl",
        "run_budget_cny": 3.0,
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


if __name__ == "__main__":
    unittest.main()
