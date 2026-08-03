"""Validate the pre-registered real A/B capability comparisons for round 087."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:  # Support both `python scripts/...` and module-based unit tests.
    from scripts.check_082_report_fidelity import measure as fidelity_measure
    from scripts.check_087_report_shape import measure as shape_measure
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI subprocess test.
    from check_082_report_fidelity import measure as fidelity_measure
    from check_087_report_shape import measure as shape_measure


CAPABILITIES = (
    "NUMERIC_CHECK",
    "RESEARCH_LOOP",
    "CONTEXT_PACKER",
    "TRAJECTORY_RECORD",
    "SKILL_PACKS",
    "SEMANTIC_JUDGE",
    "PROGRESSIVE_DELIVERY",
    "DECISION_WEAVING",
)
LOWER_IS_BETTER = (
    "reader_visible_lines",
    "boilerplate_lines",
    "audit_sections_in_report",
    "metrics_explained_gap",
    "analysis_false_positives",
)
HIGHER_IS_BETTER = ("metrics_answered", "derived_metrics_with_provenance")


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _package_record(path: Path) -> dict[str, Any]:
    manifest = _load_json(path / "audit_bundle" / "manifest.json")
    request = _load_json(path / "request.json")
    if not isinstance(manifest, dict) or not isinstance(request, dict):
        raise ValueError(f"invalid package JSON: {path}")
    fidelity = fidelity_measure(path)
    shape = shape_measure((path / "report.md").read_text(encoding="utf-8"))
    return {
        "manifest": manifest,
        "request": request,
        "shape": shape,
        "fidelity": {
            "sampled_numbers": fidelity.sampled_numbers,
            "footnote_misrefs": fidelity.footnote_misrefs,
            "magnitude_mismatches": fidelity.magnitude_mismatches,
        },
    }


def _shape_valid(values: dict[str, int]) -> bool:
    return (
        values["reader_visible_lines"] <= 40
        and values["boilerplate_lines"] == 0
        and values["audit_sections_in_report"] == 0
        and values["metrics_answered"] + values["metrics_explained_gap"]
        == values["metrics_requested"]
        and values["derived_metrics_with_provenance"] >= 1
        and values["analysis_false_positives"] == 0
    )


def _promoted(off: dict[str, Any], on: dict[str, Any]) -> bool:
    off_shape = off["shape"]
    on_shape = on["shape"]
    if off_shape["metrics_requested"] != on_shape["metrics_requested"]:
        return False
    improvements = [
        on_shape[key] < off_shape[key]
        for key in LOWER_IS_BETTER
    ] + [
        on_shape[key] > off_shape[key]
        for key in HIGHER_IS_BETTER
    ]
    regressions = [
        on_shape[key] > off_shape[key]
        for key in LOWER_IS_BETTER
    ] + [
        on_shape[key] < off_shape[key]
        for key in HIGHER_IS_BETTER
    ]
    return (
        any(improvements)
        and not any(regressions)
        and _shape_valid(off_shape)
        and _shape_valid(on_shape)
        and off["fidelity"]["footnote_misrefs"] == 0
        and on["fidelity"]["footnote_misrefs"] == 0
        and off["fidelity"]["magnitude_mismatches"] == 0
        and on["fidelity"]["magnitude_mismatches"] == 0
    )


def _single_flag_violation(
    capability: str,
    off: dict[str, Any],
    on: dict[str, Any],
    off_commit: object,
    on_commit: object,
) -> str | None:
    if off_commit != on_commit or not isinstance(off_commit, str) or not off_commit:
        return "commits differ or are missing"
    if off["request"] != on["request"]:
        return "requests differ"
    off_manifest = off["manifest"]
    on_manifest = on["manifest"]
    for key in ("mode", "retrieval_index_version", "domain"):
        if off_manifest.get(key) != on_manifest.get(key):
            return f"manifest {key} differs"
    off_flags = off_manifest.get("flags")
    on_flags = on_manifest.get("flags")
    if not isinstance(off_flags, dict) or not isinstance(on_flags, dict):
        return "manifest flags are missing"
    differing = sorted(
        key for key in set(off_flags) | set(on_flags) if off_flags.get(key) != on_flags.get(key)
    )
    expected = f"{capability}_ENABLED"
    if differing != [expected] or off_flags.get(expected) is not False or on_flags.get(expected) is not True:
        return f"flag differences={differing!r}, expected only {expected} false→true"
    return None


def validate(results_root: Path) -> tuple[dict[str, int], list[str]]:
    payload = _load_json(results_root / "results.json")
    pairs = payload.get("pairs") if isinstance(payload, dict) else None
    if not isinstance(pairs, list):
        raise ValueError("results.json must contain a pairs list")
    by_capability = {
        item.get("capability"): item
        for item in pairs
        if isinstance(item, dict) and isinstance(item.get("capability"), str)
    }
    failures: list[str] = []
    outcomes = {"promoted": 0, "kept_off": 0, "undecided": 0}
    violations = 0
    for capability in CAPABILITIES:
        item = by_capability.get(capability)
        if item is None:
            failures.append(f"missing capability={capability}")
            outcomes["undecided"] += 1
            continue
        try:
            off_path = (results_root / str(item["off_package"])).resolve()
            on_path = (results_root / str(item["on_package"])).resolve()
            off = _package_record(off_path)
            on = _package_record(on_path)
        except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"{capability}: invalid package record: {exc}")
            outcomes["undecided"] += 1
            continue
        violation = _single_flag_violation(
            capability,
            off,
            on,
            item.get("off_commit"),
            item.get("on_commit"),
        )
        if violation:
            violations += 1
            failures.append(f"{capability}: {violation}")
            outcomes["undecided"] += 1
            continue
        observed = "promoted" if _promoted(off, on) else "kept_off"
        if item.get("decision") != observed:
            failures.append(
                f"{capability}: declared={item.get('decision')!r} recomputed={observed!r}"
            )
            outcomes["undecided"] += 1
            continue
        outcomes[observed] += 1
    if len(by_capability) != len(CAPABILITIES):
        failures.append("results.json must list each pre-registered capability exactly once")
    values = {
        "capabilities_tested": len(CAPABILITIES),
        "paired_runs": 2 * len(by_capability),
        "single_flag_violations": violations,
        **outcomes,
    }
    return values, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    try:
        values, failures = validate(args.results)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        values = {
            "capabilities_tested": 0,
            "paired_runs": 0,
            "single_flag_violations": 0,
            "promoted": 0,
            "kept_off": 0,
            "undecided": 1,
        }
        failures = [str(exc)]
    for key in (
        "capabilities_tested",
        "paired_runs",
        "single_flag_violations",
        "promoted",
        "kept_off",
        "undecided",
    ):
        print(f"{key}={values[key]}")
    if failures:
        print("; ".join(failures))
    valid = (
        values["capabilities_tested"] == 8
        and values["single_flag_violations"] == 0
        and values["undecided"] == 0
        and not failures
    )
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
