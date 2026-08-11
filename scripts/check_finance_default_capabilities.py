"""Freeze the F09 experiment disposition and F10 finance default combination."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from deepresearch_agent.provenance.manifest import FLAG_CLASSIFICATIONS  # noqa: E402
from deepresearch_agent.settings import boolean_setting_defaults  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data/finance_default_capabilities.json"
PRESCREEN_PATH = ROOT / "data/capability_prescreen.json"
GRADUATION_PATH = ROOT / "data/capability_graduation.json"
README_PATH = ROOT / "README.md"
EVALUATION_PATH = ROOT / "docs/evaluation.md"
README_MARKER = (
    "九项阶段二候选能力全部为永久 opt-in，pending 为 0"
)
EVALUATION_MARKER = (
    "all nine capabilities permanently opt-in and\nzero pending, graduated, or removed entries"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(
    payload: Any,
    prescreen: Any,
    graduation: Any,
    *,
    defaults: dict[str, bool] | None = None,
    classifications: dict[str, str] | None = None,
    readme: str | None = None,
    evaluation_doc: str | None = None,
) -> list[str]:
    if not all(isinstance(item, dict) for item in (payload, prescreen, graduation)):
        return ["finance default, pre-screen and graduation registries must be objects"]
    failures: list[str] = []
    if payload.get("schema_version") != "finance-default-capabilities-v1":
        failures.append("schema_version must be finance-default-capabilities-v1")
    if payload.get("round") != 157:
        failures.append("round must be 157")

    f09 = payload.get("f09", {})
    expected_candidates = len(prescreen.get("paid_experiment_candidates", []))
    if f09.get("candidate_experiments") != expected_candidates:
        failures.append("F09 candidate count must equal the F08 pre-screen")
    if expected_candidates == 0:
        expected_zero = {
            "candidate_experiments": 0,
            "started_experiments": 0,
            "completed_experiments": 0,
            "status": "not_applicable_no_candidates",
            "cost_cny": 0,
        }
        if f09 != expected_zero:
            failures.append("F09 must start zero experiments when pre-screen has zero candidates")

    dispositions = payload.get("capability_dispositions", {})
    prescreen_caps = prescreen.get("capabilities", {})
    graduation_caps = graduation.get("capabilities", {})
    if set(dispositions) != set(prescreen_caps):
        failures.append("F10 dispositions must cover all and only F08 capabilities")
    for name, disposition in dispositions.items():
        if disposition not in {"graduated", "removed", "opt_in"}:
            failures.append(f"{name}: invalid terminal disposition {disposition!r}")
        if graduation_caps.get(name, {}).get("status") != disposition:
            failures.append(f"{name}: disposition must match graduation registry")

    counts = {
        "pending_capabilities": sum(
            entry.get("status") == "pending" for entry in graduation_caps.values()
        ),
        "graduated_capabilities": sum(value == "graduated" for value in dispositions.values()),
        "removed_capabilities": sum(value == "removed" for value in dispositions.values()),
        "opt_in_capabilities": sum(value == "opt_in" for value in dispositions.values()),
    }
    if payload.get("f10") != counts:
        failures.append(f"F10 disposition counts must equal observed {counts}")

    observed_defaults = defaults or boolean_setting_defaults()
    if payload.get("default_flags") != observed_defaults:
        failures.append("frozen default_flags drifted from Settings")
    observed_classifications = classifications or FLAG_CLASSIFICATIONS
    for name, disposition in dispositions.items():
        if disposition == "opt_in" and observed_defaults.get(name) is not False:
            failures.append(f"{name}: opt-in capability must default false")
        if observed_classifications.get(name) != "content_affecting":
            failures.append(f"{name}: capability must remain content_affecting")

    if payload.get("paid_provider_calls") != 0:
        failures.append("R157 paid_provider_calls must equal 0")
    readme_text = README_PATH.read_text(encoding="utf-8") if readme is None else readme
    evaluation_text = (
        EVALUATION_PATH.read_text(encoding="utf-8")
        if evaluation_doc is None
        else evaluation_doc
    )
    if README_MARKER not in readme_text:
        failures.append("README finance-default statement is missing or stale")
    if EVALUATION_MARKER not in evaluation_text:
        failures.append("evaluation finance-default statement is missing or stale")
    return failures


def _self_test(
    payload: dict[str, Any], prescreen: dict[str, Any], graduation: dict[str, Any]
) -> None:
    if evaluate(payload, prescreen, graduation):
        raise SystemExit("finance_default_self_test=FAIL current registry is dirty")
    cases: dict[str, tuple[dict[str, Any], dict[str, bool] | None, str | None]] = {}

    started = copy.deepcopy(payload)
    started["f09"]["started_experiments"] = 1
    cases["unselected_experiment"] = (started, None, None)

    drifted = copy.deepcopy(payload)
    drifted["default_flags"]["RAG_ENABLED"] = True
    cases["registry_default_drift"] = (drifted, None, None)

    runtime_defaults = boolean_setting_defaults()
    runtime_defaults["RAG_ENABLED"] = True
    cases["settings_default_drift"] = (payload, runtime_defaults, None)

    cases["readme_drift"] = (
        payload,
        None,
        README_PATH.read_text(encoding="utf-8").replace(README_MARKER, "stale"),
    )

    for label, (broken, broken_defaults, broken_readme) in cases.items():
        if not evaluate(
            broken,
            prescreen,
            graduation,
            defaults=broken_defaults,
            readme=broken_readme,
        ):
            raise SystemExit(f"finance_default_self_test=FAIL accepted {label}")
    print(f"finance_default_self_test=PASS cases={len(cases) + 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--mutate",
        choices=("start-unselected", "default-drift"),
        help="Intentional negative control used to preserve failure output.",
    )
    args = parser.parse_args()
    payload = _load(REGISTRY_PATH)
    prescreen = _load(PRESCREEN_PATH)
    graduation = _load(GRADUATION_PATH)
    if args.mutate == "start-unselected":
        payload["f09"]["started_experiments"] = 1
    elif args.mutate == "default-drift":
        payload["default_flags"]["RAG_ENABLED"] = True
    if args.self_test:
        _self_test(payload, prescreen, graduation)
    failures = evaluate(payload, prescreen, graduation)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(
        "finance_default=PASS "
        f"capabilities={len(payload['capability_dispositions'])} "
        f"pending={payload['f10']['pending_capabilities']} "
        f"paid_experiments={payload['f09']['started_experiments']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
