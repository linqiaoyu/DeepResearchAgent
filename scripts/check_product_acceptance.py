"""Keep product completion pointed at one reader-visible, fully-live target."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data/product_acceptance.json"
DECISIONS = ROOT / "docs/decisions"
OPERATORS = {">=", "<=", "=="}
REQUIRED_METRICS = {
    "evidence_reachable_rate",
    "orphaned_sub_questions",
    "false_premise_failed",
}
TARGET_CONTRACT = {
    "evidence_reachable_rate": (">=", 0.6),
    "orphaned_sub_questions": ("==", 0),
    "false_premise_failed": ("==", 0),
}
TARGET_ROUND = 160


def last_published_round() -> int:
    return max(
        (int(path.name) for path in DECISIONS.iterdir() if path.is_dir() and path.name.isdigit()),
        default=0,
    )


def _proof_metrics(path: Path) -> tuple[dict[str, float], list[str]]:
    failures: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"proof result cannot be read: {type(exc).__name__}"]
    fidelity = payload.get("provider_fidelity")
    if fidelity != {"llm": "live", "retrieval": "live", "structured_data": "live"}:
        failures.append("proof result is not a three-layer live run")
    if payload.get("state_path_map") not in (None, ""):
        failures.append("proof result reuses saved states instead of running the product")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 30:
        return {}, [*failures, "proof result must contain exactly 30 cases"]
    if any(item.get("status") != "done" for item in results if isinstance(item, dict)):
        failures.append("all 30 proof cases must have status=done")
    evidence = 0
    reachable = 0
    orphaned = 0
    false_premise_failed = 0
    for item in results:
        if not isinstance(item, dict):
            failures.append("every proof case must be an object")
            continue
        evidence += int(item.get("evidence_count", 0) or 0)
        mechanical = item.get("mechanical", {})
        if not isinstance(mechanical, dict):
            mechanical = {}
        reachable += int(mechanical.get("evidence_reachable_by_reader", 0) or 0)
        orphaned += int(mechanical.get("orphaned_sub_questions", 0) or 0)
        false_premise_failed += int(item.get("false_premise_failed") is True)
    return {
        "evidence_reachable_rate": reachable / evidence if evidence else 0.0,
        "orphaned_sub_questions": float(orphaned),
        "false_premise_failed": float(false_premise_failed),
    }, failures


def _meets(actual: float, operator: str, target: float) -> bool:
    if operator == ">=":
        return actual >= target
    if operator == "<=":
        return actual <= target
    return actual == target


def evaluate(registry: Any, *, horizon: int) -> list[str]:
    failures: list[str] = []
    if not isinstance(registry, dict):
        return ["product acceptance registry must be an object"]
    cohort = registry.get("cohort")
    if not isinstance(cohort, dict) or cohort.get("questions") != 30:
        failures.append("cohort must be exactly 30 questions")
    fidelity = cohort.get("fidelity", {}) if isinstance(cohort, dict) else {}
    if fidelity != {"llm": "live", "retrieval": "live", "structured_data": "live"}:
        failures.append("cohort fidelity must require live llm, retrieval and structured_data")
    selection_rule = cohort.get("selection_rule", "") if isinstance(cohort, dict) else ""
    if "no best-of" not in str(selection_rule).lower():
        failures.append("cohort selection_rule must prohibit best-of selection")

    metrics = registry.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        failures.append("metrics must be a non-empty list")
        metrics = []
    names: list[str] = []
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            failures.append(f"metric #{index} must be an object")
            continue
        name = str(metric.get("name", ""))
        names.append(name)
        target = metric.get("target")
        if metric.get("operator") not in OPERATORS or not isinstance(target, int | float):
            failures.append(f"{name or index}: metric needs a numeric target and supported operator")
        expected = TARGET_CONTRACT.get(name)
        if expected is not None and (metric.get("operator"), target) != expected:
            failures.append(
                f"{name}: target contract is {expected[0]} {expected[1]}, "
                f"got {metric.get('operator')} {target}"
            )
        scripts = re.findall(r"scripts/[A-Za-z0-9_./]+\.py", str(metric.get("measured_by", "")))
        if not scripts:
            failures.append(f"{name or index}: measured_by must name a scripts/*.py command")
        for script in scripts:
            if not (ROOT / script).exists():
                failures.append(f"{name}: measured_by cites missing {script}")
    if set(names) != REQUIRED_METRICS or len(names) != len(REQUIRED_METRICS):
        failures.append(
            f"metrics must be exactly {sorted(REQUIRED_METRICS)}, got {sorted(names)}"
        )

    target_round = registry.get("target_round")
    if not isinstance(target_round, int):
        failures.append("target_round must be an integer")
    elif target_round != TARGET_ROUND:
        failures.append(
            f"target_round is fixed at {TARGET_ROUND}; changing the registry cannot move it"
        )
    elif target_round <= horizon and not isinstance(registry.get("proof"), dict):
        failures.append(
            f"target_round={target_round} has arrived at published round {horizon} without proof"
        )
    proof = registry.get("proof")
    if isinstance(proof, dict):
        proof_round = proof.get("round")
        if not isinstance(proof_round, int) or proof_round > horizon:
            failures.append("proof.round must be a published round")
        result_path = proof.get("result_path")
        if not isinstance(result_path, str) or not result_path.startswith("docs/decisions/"):
            failures.append("proof.result_path must name a published docs/decisions artifact")
        else:
            actual, proof_failures = _proof_metrics(ROOT / result_path)
            failures.extend(proof_failures)
            for metric in metrics:
                if not isinstance(metric, dict):
                    continue
                name = str(metric.get("name", ""))
                if name not in actual:
                    failures.append(f"proof result does not produce {name}")
                    continue
                operator = str(metric.get("operator", ""))
                target = float(metric.get("target", 0))
                if not _meets(actual[name], operator, target):
                    failures.append(
                        f"proof misses {name}: {actual[name]:.4f} {operator} {target} is false"
                    )
    return failures


def _self_test(registry: dict[str, Any], horizon: int) -> None:
    if evaluate(registry, horizon=horizon):
        raise SystemExit("product_acceptance_self_test=FAIL registry is not currently clean")
    cases = {
        "fixture_fidelity": {
            **registry,
            "cohort": {
                **registry["cohort"],
                "fidelity": {"llm": "live", "retrieval": "fixture", "structured_data": "live"},
            },
        },
        "missing_metric": {**registry, "metrics": registry["metrics"][:-1]},
        "lowered_target": {
            **registry,
            "metrics": [{**registry["metrics"][0], "target": 0.1}, *registry["metrics"][1:]],
        },
        "moved_target_round": {**registry, "target_round": TARGET_ROUND + 1},
        "deadline": {**registry, "target_round": horizon, "proof": None},
        "empty_proof": {**registry, "target_round": horizon, "proof": {}},
    }
    for label, broken in cases.items():
        if not evaluate(broken, horizon=horizon):
            raise SystemExit(f"product_acceptance_self_test=FAIL accepted {label}")
    print(f"product_acceptance_self_test=PASS cases={len(cases)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    horizon = last_published_round()
    if args.self_test:
        _self_test(registry, horizon)
    failures = evaluate(registry, horizon=horizon)
    print(
        f"product_target_round={registry.get('target_round')} last_published_round={horizon} "
        f"metrics={len(registry.get('metrics', []))} "
        f"proof={int(isinstance(registry.get('proof'), dict))}"
    )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
