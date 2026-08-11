"""Prove pairwise Agent Tech composition and complete node contracts."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
import tempfile
from pathlib import Path

from deepresearch_agent.orchestration import (
    PAIRWISE_TECHNOLOGIES,
    execute_pairwise_matrix,
    validate_contract_graph,
)
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow import DeepResearchEngine
from deepresearch_agent.workflow.contracts import workflow_contract_graph


def measure() -> dict[str, int | float]:
    runs = execute_pairwise_matrix()
    covered_pair_states = 0
    pair_count = 0
    for left, right in itertools.combinations(PAIRWISE_TECHNOLOGIES, 2):
        pair_count += 1
        observed = {
            (left in run.enabled, right in run.enabled)
            for run in runs
        }
        covered_pair_states += len(observed)

    with tempfile.TemporaryDirectory(prefix="node-contract-coverage-") as temp_dir:
        root = Path(temp_dir)
        settings = Settings(
            storage_path=root / "research.db",
            runs_root=root / "runs",
            structured_logging_enabled=False,
            run_manifest_enabled=False,
        )
        with DeepResearchEngine(settings=settings) as engine:
            contracts = engine.node_contracts
            graph = workflow_contract_graph()
            validate_contract_graph(contracts, graph)
    graph_nodes = {node for edge in graph.edges for node in edge}
    return {
        "pairwise_rows": len(runs),
        "pairwise_state_coverage": covered_pair_states / (pair_count * 4),
        "technologies_active": len(
            set().union(*(run.active for run in runs))
        ),
        "combination_failures": sum(
            bool(
                run.enabled != run.active
                or run.budget_conflicts
                or run.trajectory_conflicts
                or run.state_conflicts
            )
            for run in runs
        ),
        "budget_conflicts": sum(run.budget_conflicts for run in runs),
        "trajectory_conflicts": sum(run.trajectory_conflicts for run in runs),
        "state_conflicts": sum(run.state_conflicts for run in runs),
        "node_contract_coverage": len(graph_nodes & set(contracts))
        / len(graph_nodes),
    }


def evaluate(metrics: dict[str, int | float]) -> list[str]:
    expected = {
        "pairwise_rows": 8,
        "pairwise_state_coverage": 1.0,
        "technologies_active": 7,
        "combination_failures": 0,
        "budget_conflicts": 0,
        "trajectory_conflicts": 0,
        "state_conflicts": 0,
        "node_contract_coverage": 1.0,
    }
    return [
        f"{name}: expected {target}, got {metrics.get(name)}"
        for name, target in expected.items()
        if metrics.get(name) != target
    ]


def _self_test(metrics: dict[str, int | float]) -> None:
    if evaluate(metrics):
        raise SystemExit("pairwise_composition_self_test=FAIL production probe dirty")
    cases = {
        "missing_pair_state": {**metrics, "pairwise_state_coverage": 0.99},
        "inactive_technology": {**metrics, "technologies_active": 6},
        "budget_collision": {**metrics, "budget_conflicts": 1},
        "trajectory_collision": {**metrics, "trajectory_conflicts": 1},
        "state_collision": {**metrics, "state_conflicts": 1},
        "missing_node_contract": {**metrics, "node_contract_coverage": 0.9},
    }
    for label, broken in cases.items():
        if not evaluate(broken):
            raise SystemExit(f"pairwise_composition_self_test=FAIL accepted {label}")
    print(f"pairwise_composition_self_test=PASS cases={len(cases) + 1}")


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
