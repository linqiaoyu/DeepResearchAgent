"""A CI job that passes by skipping is the failure these guards exist to fix.

R110 found three Postgres tests that had skipped on every run since they were
written -- no DSN was ever supplied, `unittest` printed `OK (skipped=3)`, and a
whole storage backend went unexercised behind a green suite. R111 fixed that for
Postgres specifically. R112 found the Qdrant vector index in exactly the same
state and replaced both the job guard and the suite guard with ones that key off
a single declaration file, so the next service cannot repeat it.

These tests pin the two guards and the declaration they share.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_no_silent_skips, check_service_job

ROOT = Path(__file__).resolve().parents[2]


class ServiceJobGuardTests(unittest.TestCase):
    def test_it_refuses_when_the_service_is_not_configured(self) -> None:
        with mock.patch.dict("os.environ", {"DEEPRESEARCH_QDRANT_URL": ""}):
            self.assertEqual(check_service_job.run_job("qdrant-vector-index"), 1)

    def test_it_refuses_when_a_configured_run_still_skips(self) -> None:
        class _Result:
            testsRun = 3
            skipped = [(object(), "URL not set")]

            def wasSuccessful(self) -> bool:
                return True

        with mock.patch.dict("os.environ", {"DEEPRESEARCH_QDRANT_URL": "http://example.invalid"}):
            with mock.patch("unittest.TextTestRunner.run", return_value=_Result()):
                self.assertEqual(check_service_job.run_job("qdrant-vector-index"), 1)

    def test_it_passes_only_when_the_tests_actually_ran(self) -> None:
        class _Result:
            testsRun = 4
            skipped: list[tuple[object, str]] = []

            def wasSuccessful(self) -> bool:
                return True

        with mock.patch.dict("os.environ", {"DEEPRESEARCH_QDRANT_URL": "http://example.invalid"}):
            with mock.patch("unittest.TextTestRunner.run", return_value=_Result()):
                self.assertEqual(check_service_job.run_job("qdrant-vector-index"), 0)

    def test_it_refuses_a_job_name_nothing_declares(self) -> None:
        self.assertEqual(check_service_job.run_job("no-such-job"), 1)

    def test_every_declared_job_exists_in_the_workflow(self) -> None:
        self.assertEqual(check_service_job.verify_workflow(), [])

    def test_it_reports_a_declared_job_the_workflow_dropped(self) -> None:
        declarations = {
            "integration.test_ghost": {
                "requires_env": "DEEPRESEARCH_GHOST_URL",
                "covered_by_ci_job": "ghost-service",
                "reason": "declared but never wired into CI",
            }
        }
        with mock.patch.object(check_service_job, "declarations", return_value=declarations):
            failures = check_service_job.verify_workflow()
        self.assertTrue(any("ghost-service" in failure for failure in failures))


class SilentSkipGuardTests(unittest.TestCase):
    def test_an_undeclared_skip_fails(self) -> None:
        failures = check_no_silent_skips.evaluate(
            [("integration.test_new_thing.Case.test_it", "SOME_URL not set")],
            check_no_silent_skips._declared(),
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("undeclared skip", failures[0])

    def test_a_declared_skip_passes_when_its_service_is_absent(self) -> None:
        declared = {"integration.test_thing": {"requires_env": "DEEPRESEARCH_ABSENT_SERVICE"}}
        with mock.patch.dict("os.environ", {"DEEPRESEARCH_ABSENT_SERVICE": ""}):
            failures = check_no_silent_skips.evaluate(
                [("integration.test_thing.Case.test_it", "not set")], declared
            )
        self.assertEqual(failures, [])

    def test_a_declared_skip_fails_when_its_service_is_configured(self) -> None:
        declared = {"integration.test_thing": {"requires_env": "DEEPRESEARCH_PRESENT_SERVICE"}}
        with mock.patch.dict("os.environ", {"DEEPRESEARCH_PRESENT_SERVICE": "http://x.invalid"}):
            failures = check_no_silent_skips.evaluate(
                [("integration.test_thing.Case.test_it", "not set")], declared
            )
        self.assertEqual(len(failures), 1)
        self.assertIn("configured but still skipped", failures[0])


class SkipDeclarationTests(unittest.TestCase):
    def test_every_declaration_names_a_variable_a_job_and_a_reason(self) -> None:
        payload = json.loads(
            (ROOT / "data/allowed_test_skips.json").read_text(encoding="utf-8")
        )
        entries = {key: value for key, value in payload.items() if not key.startswith("_")}
        self.assertTrue(entries)
        for module, entry in entries.items():
            self.assertTrue(entry.get("requires_env"), module)
            self.assertTrue(entry.get("covered_by_ci_job"), module)
            self.assertTrue(entry.get("reason"), module)

    def test_every_declared_module_exists(self) -> None:
        for module in check_no_silent_skips._declared():
            path = ROOT / "tests" / (module.replace(".", "/") + ".py")
            self.assertTrue(path.is_file(), f"declared skip for missing module: {module}")


if __name__ == "__main__":
    unittest.main()
