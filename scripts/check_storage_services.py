"""Prove full storage contract coverage and nonzero service execution wiring."""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for _entry in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(_entry))

from deepresearch_agent.storage import StorageProtocol  # noqa: E402
from scripts import check_no_silent_skips, check_service_job  # noqa: E402
from scripts.check_storage_schema_parity import (  # noqa: E402
    compare,
    postgres_schema,
    sqlite_schema,
)


CONTRACT_PATH = ROOT / "tests/contract/test_storage_contract.py"
REQUIRED_JOBS = {"postgres-storage", "qdrant-vector-index"}


def _protocol_methods() -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(StorageProtocol, inspect.isfunction)
        if not name.startswith("_")
    }


def _contract_calls() -> set[str]:
    tree = ast.parse(CONTRACT_PATH.read_text(encoding="utf-8"))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "store"
    }


def _job_test_count(job: str) -> int:
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        check_service_job.modules_for(job)
    )
    return suite.countTestCases()


class _ZeroGreenResult(unittest.TestResult):
    testsRun = 0

    def wasSuccessful(self) -> bool:
        return True


def measure() -> dict[str, int | float]:
    methods = _protocol_methods()
    contract_calls = _contract_calls()
    contract_source = CONTRACT_PATH.read_text(encoding="utf-8")
    jobs = set(check_service_job.declared_jobs())
    workflow_failures = check_service_job.verify_workflow()
    nonzero_jobs = sum(_job_test_count(job) > 0 for job in REQUIRED_JOBS)

    configured_skip_rejections = 0
    declarations = check_no_silent_skips._declared()
    for module, entry in declarations.items():
        variable = str(entry["requires_env"]).split("|", 1)[0]
        with patch.dict(os.environ, {variable: "configured"}, clear=False):
            failures = check_no_silent_skips.evaluate(
                [(f"{module}.Probe.test_service", "service unavailable")],
                declarations,
            )
        configured_skip_rejections += bool(failures)

    zero_test_rejected = bool(
        check_service_job.evaluate_job_result(
            "qdrant-vector-index",
            _ZeroGreenResult(),
        )
    )
    return {
        "storage_protocol_methods": len(methods),
        "storage_protocol_method_coverage": len(methods & contract_calls)
        / max(1, len(methods)),
        "shared_backend_contract_entrypoints": int(
            "_assert_full_contract(SQLiteStore" in contract_source
            and "_assert_full_contract(store)" in contract_source
        )
        * 2,
        "undeclared_schema_differences": len(
            compare(sqlite_schema(), postgres_schema())
        ),
        "declared_service_jobs": len(jobs & REQUIRED_JOBS),
        "service_jobs_with_nonzero_tests": nonzero_jobs,
        "configured_skip_rejection_rate": configured_skip_rejections
        / max(1, len(declarations)),
        "zero_test_green_result_rejected": int(zero_test_rejected),
        "workflow_wiring_failures": len(workflow_failures),
    }


def evaluate(metrics: dict[str, int | float]) -> list[str]:
    expected = {
        "storage_protocol_method_coverage": 1.0,
        "shared_backend_contract_entrypoints": 2,
        "undeclared_schema_differences": 0,
        "declared_service_jobs": 2,
        "service_jobs_with_nonzero_tests": 2,
        "configured_skip_rejection_rate": 1.0,
        "zero_test_green_result_rejected": 1,
        "workflow_wiring_failures": 0,
    }
    return [
        f"{name}: expected {target}, got {metrics.get(name)}"
        for name, target in expected.items()
        if metrics.get(name) != target
    ]


def _self_test(metrics: dict[str, int | float]) -> None:
    if evaluate(metrics):
        raise SystemExit("storage_services_self_test=FAIL production probe dirty")
    cases = {
        "missing_method": {**metrics, "storage_protocol_method_coverage": 0.9},
        "schema_drift": {**metrics, "undeclared_schema_differences": 1},
        "zero_service_tests": {**metrics, "service_jobs_with_nonzero_tests": 1},
        "configured_skip": {**metrics, "configured_skip_rejection_rate": 0.5},
        "unwired_job": {**metrics, "workflow_wiring_failures": 1},
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"storage_services_self_test=FAIL accepted {label}")
    print(f"storage_services_self_test=PASS cases={len(cases) + 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    metrics = measure()
    if args.self_test:
        _self_test(metrics)
    print(json.dumps(metrics, sort_keys=True))
    failures = evaluate(metrics)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
