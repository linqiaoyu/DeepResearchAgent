from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


CI_ENV = {
    "PYTHONPATH": "src",
    "DEEPRESEARCH_MODE": "deterministic",
    "DEEPRESEARCH_SEARCH_PROVIDER": "fixture",
    "DEEPRESEARCH_STRUCTURED_DATA_PROVIDER": "fixture",
    "DEEPRESEARCH_STORAGE_PATH": "artifacts/ci_runtime/research.db",
    "DEEPRESEARCH_RUNS_ROOT": "artifacts/ci_runtime/runs",
}
CI_WORKFLOW = Path(".github/workflows/ci.yml")


def _workflow_env(path: Path) -> dict[str, str]:
    """Read the deterministic-mvp job environment without a YAML dependency."""
    lines = path.read_text(encoding="utf-8").splitlines()
    in_job = False
    in_env = False
    env: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped == "deterministic-mvp:":
            in_job = True
            continue
        if in_job and indent <= 2 and stripped and stripped != "deterministic-mvp:":
            break
        if in_job and stripped == "env:":
            in_env = True
            continue
        if in_env and indent <= 4 and stripped:
            break
        if in_env and indent > 4 and ":" in stripped:
            key, value = stripped.split(":", maxsplit=1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def check_ci_environment() -> bool:
    actual = _workflow_env(CI_WORKFLOW)
    if actual == CI_ENV:
        print("ci_env_match=true")
        return True
    print("ci_env_match=false", file=sys.stderr)
    print(f"expected={CI_ENV}", file=sys.stderr)
    print(f"actual={actual}", file=sys.stderr)
    return False


def _run(step: str, command: Sequence[str], env: dict[str, str]) -> None:
    print(f"[{step}] $ {' '.join(command)}")
    completed = subprocess.run(command, check=False, env=env, stdin=subprocess.DEVNULL)
    if completed.returncode:
        print(f"failed_step={step} returncode={completed.returncode}", file=sys.stderr)
        raise SystemExit(completed.returncode)


def _tracked_diff() -> bytes:
    completed = subprocess.run(
        ["git", "diff", "--binary"],
        check=False,
        stdout=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )
    if completed.returncode:
        raise SystemExit(completed.returncode)
    return completed.stdout


def run_gate() -> None:
    if not check_ci_environment():
        raise SystemExit(1)
    initial_tracked_diff = _tracked_diff()
    env = os.environ.copy()
    env.update(CI_ENV)
    storage_path = Path(env["DEEPRESEARCH_STORAGE_PATH"])
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.unlink(missing_ok=True)
    commands = (
        ("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]),
        (
            "domain_boundary",
            [sys.executable, "scripts/check_domain_boundary.py"],
        ),
        (
            "disclosure_fixture",
            [sys.executable, "scripts/build_disclosure_fixture.py", "--check"],
        ),
        ("settings_documentation", [sys.executable, "scripts/sync_agents_settings.py", "--check"]),
        ("doc_flag_claims", [sys.executable, "scripts/check_doc_flag_claims.py"]),
        ("agent_guidance", [sys.executable, "scripts/check_agent_guidance.py"]),
        ("prompt_drift", [sys.executable, "scripts/check_prompt_drift.py"]),
        (
            "reader_visible_contract",
            [sys.executable, "scripts/check_reader_visible_contract.py", "--self-test"],
        ),
        ("report_shape", [sys.executable, "scripts/check_087_report_shape.py", "--self-test"]),
        (
            "llm_agent_liveness",
            [sys.executable, "scripts/check_llm_agent_liveness.py", "--self-test"],
        ),
        (
            "provider_worker",
            [sys.executable, "scripts/check_provider_worker.py", "--self-test"],
        ),
        ("readme_facts", [sys.executable, "scripts/check_087_readme_facts.py", "--self-test"]),
        ("unittest", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
        ("site_build", [sys.executable, "scripts/build_site.py"]),
        (
            "site_current_facts",
            [
                sys.executable,
                "scripts/check_087_site_facts.py",
                "--dist",
                "site/dist",
                "--facts",
                "data/demo/live_validation_087.json",
            ],
        ),
        ("demo_smoke", [sys.executable, "scripts/run_demo.py", "--output", "artifacts/ci_demo/report.md"]),
        (
            "eval_smoke",
            [
                sys.executable,
                "scripts/run_eval.py",
                "--limit",
                "5",
                "--compare-baseline",
                "--baseline-path",
                "data/eval_baseline_v2.json",
                "--output",
                "artifacts/ci_eval/latest_metrics.json",
            ],
        ),
    )
    for step, command in commands:
        _run(step, command, env)
    if _tracked_diff() != initial_tracked_diff:
        print("failed_step=tracked_files_unchanged", file=sys.stderr)
        raise SystemExit(1)
    print("[tracked_files_unchanged] gate created no tracked changes")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local equivalent of CI.")
    parser.add_argument("--check-ci-env", action="store_true")
    args = parser.parse_args()
    if args.check_ci_env:
        raise SystemExit(0 if check_ci_environment() else 1)
    run_gate()


if __name__ == "__main__":
    main()
