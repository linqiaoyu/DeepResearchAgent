"""Refuse an external request budget that can throw away the run's work.

R119. R113's Q03 and Q05 delivered zero sources and zero evidence:

    terminal_failure = "run-wide web fetch request budget exhausted
                        for tavily_search: 20/20"

Six searches and twenty fetches had already succeeded. The twenty-first fetch
was refused, the exception unwound the whole graph, and everything those
branches had collected was discarded before `research_join` could merge it. Ten
of the twelve gold facts the golden set never saw belong to those two questions,
so the largest remaining retrieval gap was not a research strategy at all.

AGENTS.md section 6 requires every external tool to have "有界 timeout、retry、
请求预算和显式降级". The budget existed; the degradation did not.

The instance was one branch of one method. The class is *every* run-wide
external request budget, so this guard enumerates them from `Settings` and fails
closed on one that is not registered in `data/budget_degradation.json`. A
registered budget must either

* ``degrade`` -- and name a test that proves an exhausted budget keeps the work
  already done; the guard runs that test's module and requires it to pass, so a
  registration cannot outlive the behaviour it claims; or
* ``terminate`` -- and say why, with the count of such budgets held to a ratchet
  that may only shrink.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

REGISTRY_PATH = PROJECT_ROOT / "data" / "budget_degradation.json"
SETTINGS_PATH = PROJECT_ROOT / "src" / "deepresearch_agent" / "settings.py"
VALID_DISPOSITIONS = {"degrade", "terminate"}

#: A run-wide cap on how many external requests may be issued. Named by shape so
#: a new one cannot be added without this guard noticing.
_BUDGET_FIELD_RE = re.compile(
    r"^\s{4}(max_\w*(?:search|fetch)\w*_per_run)\s*:\s*int\s*=", re.MULTILINE
)


def declared_budgets() -> list[str]:
    source = SETTINGS_PATH.read_text(encoding="utf-8")
    return sorted(set(_BUDGET_FIELD_RE.findall(source)))


def check_registry(registry: dict[str, Any], budgets: list[str]) -> list[str]:
    errors: list[str] = []
    entries = registry["budgets"]
    for name in budgets:
        entry = entries.get(name)
        if entry is None:
            errors.append(f"budget {name} is declared in Settings and not registered")
            continue
        disposition = entry.get("disposition")
        if disposition not in VALID_DISPOSITIONS:
            errors.append(f"budget {name} has unknown disposition {disposition!r}")
            continue
        if not str(entry.get("surface", "")).strip():
            errors.append(f"budget {name} must name the surface that handles it")
        if disposition == "degrade" and not str(entry.get("proof", "")).strip():
            errors.append(
                f"budget {name} degrades and names no test proving the work is kept"
            )
        if disposition == "terminate" and not str(entry.get("note", "")).strip():
            errors.append(f"budget {name} terminates and does not say why")
    for name in entries:
        if name not in budgets:
            errors.append(f"budget {name} is registered and no longer declared in Settings")
    terminating = [
        name
        for name, entry in entries.items()
        if entry.get("disposition") == "terminate"
    ]
    ratchet = int(registry["terminate_allowed_ratchet"])
    if len(terminating) > ratchet:
        errors.append(
            f"{len(terminating)} budget(s) terminate the run, ratchet is {ratchet}: {sorted(terminating)}"
        )
    return errors


def _proof_modules(registry: dict[str, Any]) -> list[str]:
    modules: set[str] = set()
    for entry in registry["budgets"].values():
        proof = str(entry.get("proof", ""))
        if "::" not in proof:
            continue
        path = proof.split("::", 1)[0]
        modules.add(
            path.removeprefix("tests/").removesuffix(".py").replace("/", ".")
        )
    return sorted(modules)


def run_proofs(registry: dict[str, Any]) -> list[str]:
    """A registration that names a test is only worth the test passing."""

    errors: list[str] = []
    for module in _proof_modules(registry):
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", module],
            cwd=PROJECT_ROOT,
            env={
                "PYTHONPATH": f"{PROJECT_ROOT / 'src'}:{PROJECT_ROOT / 'tests'}:{PROJECT_ROOT}",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PATH": "/usr/bin:/bin",
            },
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            errors.append(f"proof module {module} failed:\n{completed.stderr[-800:]}")
    return errors


def _self_test(registry: dict[str, Any], budgets: list[str]) -> int:
    failures = 0

    shipped = check_registry(registry, budgets)
    print(f"[self-test] shipped registry: {len(shipped)} error(s)")
    for error in shipped:
        print(f"[self-test]   {error}")
    if shipped:
        failures += 1

    unregistered = json.loads(json.dumps(registry))
    unregistered["budgets"].pop("max_external_fetch_requests_per_run", None)
    errors = check_registry(unregistered, budgets)
    print(f"[self-test] unregistered budget: {errors}")
    if not errors:
        print("[self-test] FAIL: an unregistered budget was accepted", file=sys.stderr)
        failures += 1

    terminating = json.loads(json.dumps(registry))
    terminating["budgets"]["max_external_fetch_requests_per_run"]["disposition"] = "terminate"
    terminating["budgets"]["max_external_fetch_requests_per_run"]["note"] = "because"
    errors = check_registry(terminating, budgets)
    print(f"[self-test] budget restored to terminate: {errors}")
    if not errors:
        print(
            "[self-test] FAIL: restoring the pre-R119 behaviour was accepted",
            file=sys.stderr,
        )
        failures += 1

    unproven = json.loads(json.dumps(registry))
    unproven["budgets"]["max_external_fetch_requests_per_run"]["proof"] = ""
    errors = check_registry(unproven, budgets)
    print(f"[self-test] degrade with no proof: {errors}")
    if not errors:
        print("[self-test] FAIL: a degrade with no proof was accepted", file=sys.stderr)
        failures += 1

    print(f"budget_degradation_self_test={'PASS' if not failures else 'FAIL'} cases=4")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--run-proofs",
        action="store_true",
        help="also execute the test modules the registry names",
    )
    args = parser.parse_args()

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    budgets = declared_budgets()
    if args.self_test:
        return _self_test(registry, budgets)

    errors = check_registry(registry, budgets)
    if args.run_proofs and not errors:
        errors.extend(run_proofs(registry))
    for error in errors:
        print(f"budget_degradation_error: {error}", file=sys.stderr)
    degrading = sum(
        1 for entry in registry["budgets"].values() if entry["disposition"] == "degrade"
    )
    print(
        f"budget_degradation={'PASS' if not errors else 'FAIL'} "
        f"declared={len(budgets)} degrade={degrading} "
        f"terminate={len(registry['budgets']) - degrading} "
        f"ratchet={registry['terminate_allowed_ratchet']}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
