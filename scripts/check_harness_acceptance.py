"""Keep Harness H2 readiness separate from finance product effectiveness."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data/harness_acceptance.json"
DECISIONS = ROOT / "docs/decisions"
TARGET_ROUND = 150
REQUIRED_STATUS = "h2_ready"
VALID_STATUSES = {"absent", "wired", REQUIRED_STATUS}
OPERATORS = {">=", "<=", "=="}
REQUIRED_TECHNOLOGIES = {
    "orchestration",
    "tool_use",
    "tool_calling",
    "planning_replanning",
    "rag",
    "mcp",
    "skills",
    "memory",
    "reflection",
    "content_security",
    "observability_replay",
    "storage_backends",
}
TARGET_CONTRACT: dict[str, dict[str, tuple[str, float]]] = {
    "orchestration": {"node_contract_coverage": ("==", 1.0)},
    "tool_use": {
        "external_call_contract_coverage": ("==", 1.0),
        "tool_error_kinds_exercised": ("==", 7.0),
    },
    "tool_calling": {
        "sequential_tool_observations": (">=", 2.0),
        "unauthorized_tool_executions": ("==", 0.0),
    },
    "planning_replanning": {
        "executed_task_plan_mapping_rate": ("==", 1.0),
        "loop_bounds_exercised": ("==", 3.0),
    },
    "rag": {
        "indexed_chunk_provenance_rate": ("==", 1.0),
        "undated_visible_documents": ("==", 0.0),
    },
    "mcp": {
        "successful_stdio_probes": (">=", 3.0),
        "resource_warnings": ("==", 0.0),
    },
    "skills": {
        "unselected_resource_reads": ("==", 0.0),
        "observable_skill_states": ("==", 4.0),
    },
    "memory": {
        "memory_kind_contract_coverage": ("==", 1.0),
        "cross_process_persistent_kinds": ("==", 3.0),
    },
    "reflection": {
        "unauthorized_reflection_adoptions": ("==", 0.0),
        "recorded_reasoner_replay_match": ("==", 1.0),
    },
    "content_security": {
        "guarded_ingress_kinds": ("==", 4.0),
        "registered_injection_successes": ("==", 0.0),
    },
    "observability_replay": {
        "harness_technology_locator_coverage": ("==", 1.0),
        "completed_report_byte_match": ("==", 1.0),
    },
    "storage_backends": {
        "storage_protocol_method_coverage": ("==", 1.0),
        "undeclared_schema_differences": ("==", 0.0),
    },
}


def last_published_round() -> int:
    return max(
        (int(path.name) for path in DECISIONS.iterdir() if path.is_dir() and path.name.isdigit()),
        default=0,
    )


def _meets(actual: float, operator: str, target: float) -> bool:
    if operator == ">=":
        return actual >= target
    if operator == "<=":
        return actual <= target
    return actual == target


def _proof_metrics(path: Path, technology: str) -> tuple[dict[str, float], list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"{technology}: proof cannot be read: {type(exc).__name__}"]
    failures: list[str] = []
    if payload.get("technology") != technology:
        failures.append(f"{technology}: proof technology does not match")
    if payload.get("status") != REQUIRED_STATUS:
        failures.append(f"{technology}: proof status must be {REQUIRED_STATUS}")
    raw_metrics = payload.get("metrics")
    if not isinstance(raw_metrics, dict):
        return {}, [*failures, f"{technology}: proof metrics must be an object"]
    metrics = {
        str(name): float(value)
        for name, value in raw_metrics.items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    return metrics, failures


def evaluate(registry: Any, *, horizon: int) -> list[str]:
    failures: list[str] = []
    if not isinstance(registry, dict):
        return ["harness acceptance registry must be an object"]
    if registry.get("target_round") != TARGET_ROUND:
        failures.append(f"target_round is fixed at {TARGET_ROUND}")
    if registry.get("required_status") != REQUIRED_STATUS:
        failures.append(f"required_status is fixed at {REQUIRED_STATUS}")
    technologies = registry.get("technologies")
    if not isinstance(technologies, dict):
        return [*failures, "technologies must be an object"]
    observed = set(technologies)
    if observed != REQUIRED_TECHNOLOGIES:
        failures.append(
            "technologies must be exactly "
            f"{sorted(REQUIRED_TECHNOLOGIES)}, got {sorted(observed)}"
        )
    for name in sorted(observed):
        entry = technologies[name]
        if not isinstance(entry, dict):
            failures.append(f"{name}: entry must be an object")
            continue
        status = entry.get("status")
        if status not in VALID_STATUSES:
            failures.append(f"{name}: invalid status {status!r}")
        for field in ("objective", "boundary"):
            if not str(entry.get(field, "")).strip():
                failures.append(f"{name}: {field} must be non-empty")
        criteria = entry.get("criteria")
        expected = TARGET_CONTRACT.get(name, {})
        if not isinstance(criteria, list):
            failures.append(f"{name}: criteria must be a list")
            criteria = []
        actual_contract: dict[str, tuple[str, float]] = {}
        for index, criterion in enumerate(criteria):
            if not isinstance(criterion, dict):
                failures.append(f"{name}: criterion #{index} must be an object")
                continue
            metric = str(criterion.get("metric", ""))
            operator = criterion.get("operator")
            target = criterion.get("target")
            if operator not in OPERATORS or not isinstance(target, int | float):
                failures.append(f"{name}/{metric or index}: criterion must be numeric")
                continue
            actual_contract[metric] = (str(operator), float(target))
            command = str(criterion.get("measured_by", ""))
            scripts = re.findall(r"scripts/[A-Za-z0-9_./]+\.py", command)
            if not scripts:
                failures.append(f"{name}/{metric}: measured_by must name scripts/*.py")
            for script in scripts:
                if not (ROOT / script).is_file():
                    failures.append(f"{name}/{metric}: measured_by cites missing {script}")
        if actual_contract != expected:
            failures.append(
                f"{name}: target contract changed; expected {expected}, got {actual_contract}"
            )
        proof = entry.get("proof")
        if status == REQUIRED_STATUS:
            if not isinstance(proof, dict):
                failures.append(f"{name}: {REQUIRED_STATUS} requires a published proof")
                continue
            proof_round = proof.get("round")
            if not isinstance(proof_round, int) or proof_round > horizon:
                failures.append(f"{name}: proof.round must be a published round")
            artifact = proof.get("artifact")
            if not isinstance(artifact, str) or not artifact.startswith("docs/decisions/"):
                failures.append(f"{name}: proof.artifact must be a published decision artifact")
                continue
            metrics, proof_failures = _proof_metrics(ROOT / artifact, name)
            failures.extend(proof_failures)
            for metric, (operator, target) in expected.items():
                if metric not in metrics:
                    failures.append(f"{name}: proof does not produce {metric}")
                elif not _meets(metrics[metric], operator, target):
                    failures.append(
                        f"{name}: proof misses {metric}: "
                        f"{metrics[metric]} {operator} {target} is false"
                    )
        elif proof is not None:
            failures.append(f"{name}: only {REQUIRED_STATUS} may carry proof")
    if horizon >= TARGET_ROUND:
        incomplete = sorted(
            name
            for name, entry in technologies.items()
            if not isinstance(entry, dict) or entry.get("status") != REQUIRED_STATUS
        )
        if incomplete:
            failures.append(
                f"Harness H2 deadline R{TARGET_ROUND} arrived without proof for {incomplete}"
            )
    return failures


def _self_test(registry: dict[str, Any], horizon: int) -> None:
    if evaluate(registry, horizon=horizon):
        raise SystemExit("harness_acceptance_self_test=FAIL registry is not currently clean")
    technologies = registry["technologies"]
    sample = "tool_calling"
    cases = {
        "missing_technology": {
            **registry,
            "technologies": {k: v for k, v in technologies.items() if k != sample},
        },
        "moved_deadline": {**registry, "target_round": TARGET_ROUND + 1},
        "weakened_target": {
            **registry,
            "technologies": {
                **technologies,
                sample: {
                    **technologies[sample],
                    "criteria": [
                        {**technologies[sample]["criteria"][0], "target": 1},
                        *technologies[sample]["criteria"][1:],
                    ],
                },
            },
        },
        "h2_without_proof": {
            **registry,
            "technologies": {
                **technologies,
                sample: {
                    key: value
                    for key, value in {
                        **technologies[sample],
                        "status": REQUIRED_STATUS,
                    }.items()
                    if key != "proof"
                },
            },
        },
    }
    for label, broken in cases.items():
        if not evaluate(broken, horizon=horizon):
            raise SystemExit(f"harness_acceptance_self_test=FAIL accepted {label}")
    if not evaluate(registry, horizon=TARGET_ROUND):
        raise SystemExit("harness_acceptance_self_test=FAIL accepted missed deadline")
    print(f"harness_acceptance_self_test=PASS cases={len(cases) + 1}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--technology", choices=sorted(REQUIRED_TECHNOLOGIES))
    args = parser.parse_args()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    horizon = last_published_round()
    if args.self_test:
        _self_test(registry, horizon)
    failures = evaluate(registry, horizon=horizon)
    technologies = registry.get("technologies", {})
    if args.technology:
        entry = technologies.get(args.technology, {})
        print(f"technology={args.technology} status={entry.get('status', 'absent')}")
    else:
        for name in sorted(REQUIRED_TECHNOLOGIES):
            entry = technologies.get(name, {})
            status = entry.get("status", "absent") if isinstance(entry, dict) else "absent"
            print(f"technology={name} status={status}")
    ready = sum(
        isinstance(entry, dict) and entry.get("status") == REQUIRED_STATUS
        for entry in technologies.values()
    )
    print(
        f"harness_target_round={TARGET_ROUND} last_published_round={horizon} "
        f"registered={len(technologies)}/{len(REQUIRED_TECHNOLOGIES)} h2_ready={ready}"
    )
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
