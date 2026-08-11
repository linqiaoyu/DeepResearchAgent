from __future__ import annotations

import argparse
import ast
import sqlite3
import tempfile
from pathlib import Path

from check_memory_lifecycle import measure as lifecycle_measure
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_TEST = ROOT / "tests" / "contract" / "test_storage_contract.py"


def _storage_contract_metrics() -> tuple[float, int]:
    tree = ast.parse(CONTRACT_TEST.read_text(encoding="utf-8"))
    methods: dict[str, ast.FunctionDef] = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    memory_contract = methods.get("_assert_memory_contract")
    full_contract = methods.get("_assert_full_contract")
    if memory_contract is None or full_contract is None:
        return 0.0, 0
    calls = {
        node.func.attr
        for node in ast.walk(memory_contract)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    required = {"write_memory_record", "list_memory_records"}
    full_calls_memory = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_assert_memory_contract"
        for node in ast.walk(full_contract)
    )
    source = CONTRACT_TEST.read_text(encoding="utf-8")
    backends = sum(
        marker in source
        for marker in (
            "_assert_full_contract(SQLiteStore(",
            "_assert_full_contract(store)",
        )
    )
    return len(calls & required) / len(required) * int(full_calls_memory), backends


def _procedural_without_reflection() -> int:
    with tempfile.TemporaryDirectory(prefix="memory-independent-write-") as raw:
        root = Path(raw)
        db_path = root / "research.db"
        settings = Settings(
            storage_path=db_path,
            runs_root=root / "runs",
            procedural_memory_enabled=True,
            reflection_enabled=False,
            structured_logging_enabled=False,
            max_critic_iter=1,
        )
        with DeepResearchEngine(settings=settings) as engine:
            engine.run(
                topic="AI Agent 在财富管理行业的落地机会研究",
                depth_level=1,
            )
        with sqlite3.connect(db_path) as connection:
            return int(
                connection.execute(
                    "SELECT count(*) FROM memory_record "
                    "WHERE namespace = 'default:finance:procedural'"
                ).fetchone()[0]
            )


def measure() -> dict[str, int | float]:
    lifecycle = lifecycle_measure()
    method_coverage, backend_count = _storage_contract_metrics()
    return {
        "memory_protocol_method_coverage": method_coverage,
        "shared_contract_backends": backend_count,
        "cross_process_persistent_kinds": lifecycle[
            "cross_process_persistent_kinds"
        ],
        "persistent_cross_process_rate": lifecycle[
            "persistent_cross_process_rate"
        ],
        "namespace_domain_tenant_leaks": lifecycle[
            "namespace_domain_tenant_leaks"
        ],
        "procedural_writes_without_reflection": (
            _procedural_without_reflection()
        ),
    }


def validate(metrics: dict[str, int | float]) -> None:
    exact = {
        "memory_protocol_method_coverage": 1.0,
        "shared_contract_backends": 2,
        "cross_process_persistent_kinds": 3,
        "persistent_cross_process_rate": 1.0,
        "namespace_domain_tenant_leaks": 0,
    }
    failures = [
        f"{name}: expected {target!r}, got {metrics.get(name)!r}"
        for name, target in exact.items()
        if metrics.get(name) != target
    ]
    if metrics.get("procedural_writes_without_reflection", 0) <= 0:
        failures.append("procedural_writes_without_reflection must be > 0")
    if failures:
        raise AssertionError("; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is required")
    metrics = measure()
    validate(metrics)
    for name, value in sorted(metrics.items()):
        print(f"{name}={value}")
    print("memory_persistence_self_test=PASS cases=6")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
