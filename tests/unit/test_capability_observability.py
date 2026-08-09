"""R110: the harness could not answer 'did this capability run?' in one place.

R109 asked that of an archived run and I got two answers wrong -- the manifest
and the trajectory are written under `runs/<research_id>/`, not into the state,
so capabilities that were plainly working were reported as unobservable. The
locator table is that answer, written down once and checked against real runs.

Measured across the 24 archived live runs: 16 of 25 declared flags are provable
from a run's own artifacts, and 9 leave no per-run evidence at all. Those 9 are
listed by the checker rather than hidden, and are the number to drive down.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_capability_observability import (
    ABSENT,
    BYPASSED,
    LOCATORS,
    RAN,
    UNPROVABLE,
    ObservabilityError,
    classify,
    report,
    validate_locator_table,
)

from deepresearch_agent.settings import boolean_setting_defaults


class LocatorTableTests(unittest.TestCase):
    def test_every_declared_flag_has_an_answer(self) -> None:
        validate_locator_table()

    def test_the_table_names_no_flag_that_does_not_exist(self) -> None:
        self.assertEqual(sorted(set(LOCATORS) - set(boolean_setting_defaults())), [])

    def test_an_undeclared_flag_is_refused_rather_than_guessed(self) -> None:
        with self.assertRaises(ObservabilityError):
            classify("NOT_A_FLAG", {}, None)


class ClassificationTests(unittest.TestCase):
    def test_a_metadata_key_proves_the_capability_ran(self) -> None:
        state = {"metadata": {"branch_budget": {"unit": "search_calls"}}}

        self.assertEqual(classify("BRANCH_BUDGET_ENABLED", state, None), RAN)

    def test_a_top_level_field_is_not_looked_for_in_metadata(self) -> None:
        """The mistake the `field` kind exists to prevent."""
        state = {"metadata": {}, "structured_output": {"comparison_table": {}}}

        self.assertEqual(classify("STRUCTURED_OUTPUT_ENABLED", state, None), RAN)

    def test_component_activity_separates_ran_from_switched_off(self) -> None:
        ran = {"metadata": {"component_activity": {"critic": {"completed": 1}}}}
        off = {
            "metadata": {
                "component_activity": {"critic": {"completed": 0, "bypassed": 1}}
            }
        }

        self.assertEqual(classify("CRITIC_ENABLED", ran, None), RAN)
        self.assertEqual(classify("CRITIC_ENABLED", off, None), BYPASSED)

    def test_an_artifact_is_proof_only_when_the_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.assertEqual(
                classify("RUN_MANIFEST_ENABLED", {}, directory), ABSENT
            )
            (directory / "manifest.json").write_text("{}", encoding="utf-8")
            self.assertEqual(classify("RUN_MANIFEST_ENABLED", {}, directory), RAN)

    def test_a_capability_with_no_evidence_is_reported_not_assumed(self) -> None:
        self.assertEqual(classify("TOOL_CONTRACT_ENABLED", {}, None), UNPROVABLE)

    def test_an_empty_run_proves_nothing(self) -> None:
        rows = report({"metadata": {}}, None)

        self.assertNotIn(RAN, set(rows.values()))


class MeasuredGapTests(unittest.TestCase):
    def test_the_unprovable_set_is_explicit(self) -> None:
        """A silent shrink of this list would hide a lost signal."""
        unprovable = sorted(
            flag for flag, locator in LOCATORS.items() if locator.kind is None
        )

        self.assertEqual(
            unprovable,
            [
                "CONFIG_FAIL_FAST_ENABLED",
                "INJECTION_GUARD_ENABLED",
                "NUMERIC_CHECK_ENABLED",
                "PROGRESSIVE_DELIVERY_ENABLED",
                "RERANK_ENABLED",
                "RERANK_FAIL_OPEN",
                "RESEARCH_LOOP_ENABLED",
                "STRUCTURED_LOGGING_ENABLED",
                "TOOL_CONTRACT_ENABLED",
            ],
        )

    def test_most_capabilities_are_provable(self) -> None:
        provable = [f for f, loc in LOCATORS.items() if loc.kind is not None]

        self.assertEqual(len(provable), 16)


if __name__ == "__main__":
    unittest.main()
