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
    ACTIVE,
    BYPASSED,
    LOCATORS,
    RAN,
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

    def test_a_composed_capability_claims_active_not_ran(self) -> None:
        """Wired into the run is knowable; having done work is not."""
        state = {
            "metadata": {
                "component_activity": {
                    "tool_contract": {"completed": 0, "composed": 1}
                }
            }
        }

        self.assertEqual(classify("TOOL_CONTRACT_ENABLED", state, None), ACTIVE)

    def test_a_capability_with_no_record_is_absent_not_assumed(self) -> None:
        self.assertEqual(classify("TOOL_CONTRACT_ENABLED", {}, None), ABSENT)

    def test_an_empty_run_proves_nothing(self) -> None:
        rows = report({"metadata": {}}, None)

        self.assertNotIn(RAN, set(rows.values()))
        self.assertNotIn(ACTIVE, set(rows.values()))


class MeasuredGapTests(unittest.TestCase):
    def test_every_declared_capability_is_provable_from_a_run(self) -> None:
        """R110 measured 9 with no per-run evidence; R111 closed all nine."""
        unprovable = sorted(
            flag for flag, locator in LOCATORS.items() if locator.kind is None
        )

        self.assertEqual(unprovable, [])

    def test_every_classified_flag_has_a_locator(self) -> None:
        """R123: this asserted the literal 25 and broke when a 26th flag landed.

        The count was incidental; what the test is for is that no manifest flag
        exists without a way to prove it ran. Deriving the expected set from the
        classification table asserts exactly that, and a new flag added without
        a locator now fails here instead of shifting a number.
        """

        from deepresearch_agent.provenance.manifest import FLAG_CLASSIFICATIONS

        provable = {flag for flag, loc in LOCATORS.items() if loc.kind is not None}

        self.assertEqual(sorted(set(FLAG_CLASSIFICATIONS) - provable), [])
        self.assertEqual(sorted(provable - set(FLAG_CLASSIFICATIONS)), [])


if __name__ == "__main__":
    unittest.main()
