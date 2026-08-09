"""R111: a CI job that passes by skipping is the failure it was added to fix.

R110 found three Postgres tests that had skipped on every run since they were
written -- no DSN was ever supplied, `unittest` printed `OK (skipped=3)`, and a
whole storage backend went unexercised behind a green suite. Adding a job does
not fix that by itself: if the DSN stops reaching a server, the same tests skip
and the job still passes.

This guard asserts the opposite, and these tests pin the guard.
"""

from __future__ import annotations

import unittest
from unittest import mock

from scripts.check_postgres_job import DSN_VARIABLES, POSTGRES_MODULES, main


class PostgresJobGuardTests(unittest.TestCase):
    def test_it_refuses_when_no_dsn_is_configured(self) -> None:
        with mock.patch.dict("os.environ", {name: "" for name in DSN_VARIABLES}):
            with mock.patch("sys.argv", ["check_postgres_job.py"]):
                self.assertEqual(main(), 1)

    def test_it_refuses_when_a_configured_run_still_skips(self) -> None:
        class _Result:
            testsRun = 3
            skipped = [(object(), "DSN not set")]

            def wasSuccessful(self) -> bool:
                return True

        with mock.patch.dict(
            "os.environ", {DSN_VARIABLES[0]: "postgresql://example.invalid/db"}
        ):
            with mock.patch("sys.argv", ["check_postgres_job.py"]):
                with mock.patch(
                    "unittest.TextTestRunner.run", return_value=_Result()
                ):
                    self.assertEqual(main(), 1)

    def test_it_passes_only_when_the_tests_actually_ran(self) -> None:
        class _Result:
            testsRun = 3
            skipped: list[tuple[object, str]] = []

            def wasSuccessful(self) -> bool:
                return True

        with mock.patch.dict(
            "os.environ", {DSN_VARIABLES[0]: "postgresql://example.invalid/db"}
        ):
            with mock.patch("sys.argv", ["check_postgres_job.py"]):
                with mock.patch(
                    "unittest.TextTestRunner.run", return_value=_Result()
                ):
                    self.assertEqual(main(), 0)

    def test_the_workflow_runs_the_modules_this_guard_asserts(self) -> None:
        from pathlib import Path

        workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("postgres-storage:", workflow)
        self.assertIn("check_postgres_job.py", workflow)
        for module in POSTGRES_MODULES:
            self.assertIn(module, workflow)


if __name__ == "__main__":
    unittest.main()
