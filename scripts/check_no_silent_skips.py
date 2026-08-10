"""Refuse a suite that passes because tests did not run.

R110 found three Postgres tests that had skipped on every run since they were
written: no DSN was ever supplied, `unittest` reported `OK (skipped=3)`, and a
whole storage backend went unexercised while the suite looked green. R111 added
a guard -- and hardcoded it to the two Postgres modules.

R112 then found `tests/integration/test_qdrant_integration.py` skipping for the
identical reason, with no CI job supplying `DEEPRESEARCH_QDRANT_URL`. The vector
index had never executed once. The lesson of R110 had been applied to the
instance rather than to the class, so the next backend repeated it exactly.

This generalises it. Every skip in the suite must be declared in
``data/allowed_test_skips.json`` together with the environment variable that
makes it run. A skip nobody declared fails. A declared skip whose variable *is*
configured fails too -- that is the R110 case, where the service was there and
the test still did not run.

`--self-test` proves the check can fail by asserting an undeclared skip is
rejected.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Reproduce what `python -m unittest discover -s tests` sees from the repo root:
# the root itself (tests import `scripts.*`), `src`, and the tests directory
# that discovery uses as its top level.
for _entry in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(_entry))

ALLOWLIST_PATH = ROOT / "data/allowed_test_skips.json"


def _declared() -> dict[str, dict[str, str]]:
    payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    return {key: value for key, value in payload.items() if not key.startswith("_")}


def _test_id_prefix(test_id: str) -> str:
    """Reduce a test id to the module path the allowlist keys on."""

    parts = test_id.split(".")
    return ".".join(parts[:-2]) if len(parts) > 2 else test_id


def evaluate(skipped: list[tuple[str, str]], declared: dict[str, dict[str, str]]) -> list[str]:
    """Return every skip that is undeclared, or declared but should have run."""

    failures: list[str] = []
    for test_id, reason in skipped:
        module = _test_id_prefix(test_id)
        entry = declared.get(module)
        if entry is None:
            failures.append(
                f"undeclared skip: {test_id} ({reason}). Declare it in "
                f"{ALLOWLIST_PATH.relative_to(ROOT)} with the variable that makes it run, "
                f"or the code it covers is never exercised."
            )
            continue
        variables = [name.strip() for name in str(entry["requires_env"]).split("|")]
        if any(os.getenv(name, "").strip() for name in variables):
            failures.append(
                f"configured but still skipped: {test_id} ({reason}). "
                f"{' or '.join(variables)} is set, so this test must run."
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    declared = _declared()

    if args.self_test:
        undeclared = evaluate([("pkg.module.Case.test_thing", "no reason given")], declared)
        if not undeclared:
            print(
                "no_silent_skips=FAIL self-test did not reject an undeclared skip",
                file=sys.stderr,
            )
            return 1
        configured = evaluate(
            [(f"{next(iter(declared))}.Case.test_thing", "skipped")],
            {next(iter(declared)): {"requires_env": "PATH"}},
        )
        if not configured:
            print(
                "no_silent_skips=FAIL self-test did not reject a configured-but-skipped test",
                file=sys.stderr,
            )
            return 1

    # This *is* the suite run, not a second one. The gate calls it in place of
    # a bare `unittest discover`, so the tests execute once and both assertions
    # -- they passed, and the ones that skipped were declared -- come from the
    # same result object.
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=1, stream=sys.stdout).run(suite)
    skipped = [(test.id(), reason) for test, reason in result.skipped]
    failures = evaluate(skipped, declared)

    if not result.wasSuccessful():
        print("no_silent_skips=FAIL the suite itself did not pass", file=sys.stderr)
        return 1
    if failures:
        for failure in failures:
            print(f"no_silent_skips=FAIL {failure}", file=sys.stderr)
        return 1
    ran = result.testsRun - len(skipped)
    print(
        f"no_silent_skips=PASS tests_run={ran} skipped={len(skipped)} "
        f"all_declared=true undeclared=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
