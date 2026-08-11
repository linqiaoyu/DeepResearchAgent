"""Refuse a service CI job that passed because its tests skipped.

R110 found three Postgres tests that had skipped on every run since they were
written. R111 added a job and a guard, both hardcoded to Postgres. R112 then
found the Qdrant vector index in the identical state -- tests that skip, no job,
never executed -- because the fix had been written for the instance instead of
the class.

So the mapping lives in one place now. ``data/allowed_test_skips.json`` says
which modules may skip, which environment variable makes each run, and which CI
job is responsible for supplying it. This guard reads that file:

* ``--job <name>`` runs every module that job owns and fails if any skipped,
  or if the variable that enables them is not configured.
* ``--verify-workflow`` fails when a declared job does not exist in the
  workflow, so declaring a skip cannot be a way to avoid running the code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _entry in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(_entry))

ALLOWLIST_PATH = ROOT / "data/allowed_test_skips.json"
WORKFLOW_PATH = ROOT / ".github/workflows/ci.yml"


def declarations() -> dict[str, dict[str, str]]:
    payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return {key: value for key, value in payload.items() if not key.startswith("_")}


def modules_for(job: str) -> list[str]:
    return sorted(
        module
        for module, entry in declarations().items()
        if entry.get("covered_by_ci_job") == job
    )


def declared_jobs() -> list[str]:
    return sorted({entry["covered_by_ci_job"] for entry in declarations().values()})


def verify_workflow() -> list[str]:
    """Every job the allowlist leans on must exist and run this guard."""

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    failures: list[str] = []
    for job in declared_jobs():
        if f"{job}:" not in workflow:
            failures.append(f"allowlist names CI job {job!r}, which the workflow does not define")
            continue
        if f"--job {job}" not in workflow:
            failures.append(f"CI job {job!r} does not run this guard with --job {job}")
        for module in modules_for(job):
            if module not in workflow:
                failures.append(f"CI job {job!r} does not run declared module {module!r}")
    return failures


def evaluate_job_result(job: str, result: unittest.TestResult) -> list[str]:
    """Reject green-looking service runs that executed no usable tests."""

    failures: list[str] = []
    if result.testsRun <= 0:
        failures.append(f"job {job!r} executed zero tests")
    if result.skipped:
        failures.append(
            f"{len(result.skipped)} test(s) skipped with the service configured: "
            + "; ".join(reason for _test, reason in result.skipped)
        )
    if not result.wasSuccessful():
        failures.append(f"job {job!r} tests did not pass")
    return failures


def run_job(job: str) -> int:
    modules = modules_for(job)
    if not modules:
        print(f"service_job=FAIL no modules declared for job {job!r}", file=sys.stderr)
        return 1
    required = {
        name.strip()
        for module in modules
        for name in str(declarations()[module]["requires_env"]).split("|")
    }
    if not any(os.getenv(name, "").strip() for name in sorted(required)):
        print(
            f"service_job=FAIL job {job!r} has none of {sorted(required)} configured; "
            "its tests would skip and the job would pass having run nothing",
            file=sys.stderr,
        )
        return 1

    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    failures = evaluate_job_result(job, result)
    if failures:
        for failure in failures:
            print(f"service_job=FAIL {failure}", file=sys.stderr)
        return 1
    print(f"service_job=PASS job={job} modules={len(modules)} tests_run={result.testsRun} skipped=0")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job")
    parser.add_argument("--verify-workflow", action="store_true")
    args = parser.parse_args()

    if args.verify_workflow:
        failures = verify_workflow()
        for failure in failures:
            print(f"service_job=FAIL {failure}", file=sys.stderr)
        if failures:
            return 1
        print(f"service_job=PASS declared_jobs={','.join(declared_jobs())} workflow_verified=true")
        return 0

    if not args.job:
        parser.error("--job or --verify-workflow is required")
    return run_job(args.job)


if __name__ == "__main__":
    raise SystemExit(main())
