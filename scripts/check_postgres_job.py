"""Refuse a Postgres run that passed by skipping.

R110 found three Postgres tests that had skipped on every run since they were
written: no DSN was ever supplied, `unittest` reported `OK (skipped=3)`, and a
whole storage backend went unexercised while the suite looked green.

Adding a CI job does not fix that on its own -- if the DSN stops reaching a
server, the same tests skip again and the job still passes. This asserts the
opposite: with a DSN configured, those tests must actually run.
"""

from __future__ import annotations

import argparse
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

POSTGRES_MODULES = (
    "contract.test_storage_contract",
    "integration.test_postgres_storage_live",
)
DSN_VARIABLES = ("DEEPRESEARCH_POSTGRES_DSN", "DEEPRESEARCH_PG_DSN")


def _configured() -> bool:
    return any(os.getenv(name, "").strip() for name in DSN_VARIABLES)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        # Without a DSN the guard must refuse to claim anything, rather than
        # pass because nothing ran.
        if _configured():
            print("postgres_job=PASS dsn configured")
            return 0
        print("postgres_job=SKIP no DSN configured; nothing asserted")
        return 0

    if not _configured():
        print(
            "postgres_job=FAIL no DSN in " + " or ".join(DSN_VARIABLES),
            file=sys.stderr,
        )
        return 1

    suite = unittest.defaultTestLoader.loadTestsFromNames(POSTGRES_MODULES)
    result = unittest.TextTestRunner(verbosity=0).run(suite)
    ran = result.testsRun - len(result.skipped)
    if result.skipped:
        print(
            f"postgres_job=FAIL {len(result.skipped)} test(s) skipped with a DSN "
            "configured: " + "; ".join(reason for _test, reason in result.skipped),
            file=sys.stderr,
        )
        return 1
    if not result.wasSuccessful():
        print("postgres_job=FAIL tests did not pass", file=sys.stderr)
        return 1
    print(f"postgres_job=PASS tests_run={ran} skipped=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
