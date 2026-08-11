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
        # R125: a check file outside every runner is documentation disguised as
        # enforcement. Run this first so new orphan guards cannot accumulate.
        (
            "guard_wiring",
            [sys.executable, "scripts/check_guard_wiring.py", "--self-test"],
        ),
        (
            "workflow_module_size",
            [sys.executable, "scripts/check_workflow_module_size.py"],
        ),
        (
            "capability_graduation",
            [sys.executable, "scripts/check_capability_graduation.py", "--self-test"],
        ),
        (
            "harness_acceptance",
            [sys.executable, "scripts/check_harness_acceptance.py", "--self-test"],
        ),
        (
            "product_acceptance",
            [sys.executable, "scripts/check_product_acceptance.py", "--self-test"],
        ),
        ("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]),
        # Scoped to the surfaces where two implementations must agree; the file
        # list in pyproject.toml is a ratchet that may only grow. Ruff cannot
        # see the class of defect this catches -- a backend that inherits
        # another's __init__ without calling it, or drops a protocol method.
        ("mypy", [sys.executable, "-m", "mypy"]),
        (
            "domain_boundary",
            [sys.executable, "scripts/check_domain_boundary.py", "--self-test"],
        ),
        (
            "external_call_closure",
            [sys.executable, "scripts/check_external_call_closure.py", "--self-test"],
        ),
        (
            "tool_lifecycle",
            [sys.executable, "scripts/check_tool_lifecycle.py", "--self-test"],
        ),
        (
            "tool_calling_loop",
            [sys.executable, "scripts/check_tool_calling_loop.py", "--self-test"],
        ),
        (
            "planning_contract",
            [sys.executable, "scripts/check_planning_contract.py", "--self-test"],
        ),
        (
            "replanning_loop",
            [sys.executable, "scripts/check_replanning_loop.py", "--self-test"],
        ),
        (
            "rag_ingestion",
            [sys.executable, "scripts/check_rag_ingestion.py", "--self-test"],
        ),
        (
            "rag_retrieval",
            [sys.executable, "scripts/check_rag_retrieval.py", "--self-test"],
        ),
        (
            "mcp_interop",
            [sys.executable, "scripts/check_mcp_interop.py", "--self-test"],
        ),
        (
            "mcp_safety",
            [sys.executable, "scripts/check_mcp_safety.py", "--self-test"],
        ),
        (
            "storage_schema_parity",
            [sys.executable, "scripts/check_storage_schema_parity.py", "--self-test"],
        ),
        (
            "disclosure_lookahead",
            [sys.executable, "scripts/check_disclosure_lookahead.py", "--self-test"],
        ),
        (
            "service_jobs_declared",
            [sys.executable, "scripts/check_service_job.py", "--verify-workflow"],
        ),
        # R114: a test that bounds a real clock from above is measuring machine
        # load, not behaviour. It passes alone and fails in a full suite, which
        # is the shape that wastes a round diagnosing a green product.
        (
            "wall_clock_assertions",
            [sys.executable, "scripts/check_wall_clock_assertions.py", "--self-test"],
        ),
        (
            "disclosure_fixture",
            [sys.executable, "scripts/build_disclosure_fixture.py", "--check"],
        ),
        # R115: the golden set freezes behavioural requirements that no scoring
        # code read. The one metric that claimed to cover `refute_premise`
        # substring-matched a prose behaviour description, so it could not
        # return True, and R113 published 0/30 for a report that asserted the
        # premise in its first sentence.
        (
            "behavioral_criteria",
            [sys.executable, "scripts/check_behavioral_criteria.py", "--self-test"],
        ),
        (
            "behavioral_criteria_registered",
            [sys.executable, "scripts/check_behavioral_criteria.py"],
        ),
        # R116: the reporter model decides what to write from every packed
        # Evidence item, so a sub-question it passes over reaches the reader as
        # silence. 8 of 80 sub-questions on the R113 live set arrived that way.
        (
            "evidence_reaches_reader",
            [sys.executable, "scripts/check_evidence_reaches_reader.py", "--self-test"],
        ),
        # R117: 83% of every reference line the R113 reports delivered was a
        # line the body never pointed to, and 969 of them were single records
        # of a provider series.
        (
            "reference_list_hygiene",
            [sys.executable, "scripts/check_reference_list_hygiene.py", "--self-test"],
        ),
        # R119: an exhausted external request budget used to unwind the graph,
        # discarding the sources the run had already collected. Two of the 30
        # R113 questions delivered zero evidence that way.
        (
            "budget_degradation",
            [sys.executable, "scripts/check_budget_degradation.py", "--self-test"],
        ),
        (
            "budget_degradation_registered",
            [sys.executable, "scripts/check_budget_degradation.py", "--run-proofs"],
        ),
        ("settings_documentation", [sys.executable, "scripts/sync_agents_settings.py", "--check"]),
        ("doc_flag_claims", [sys.executable, "scripts/check_doc_flag_claims.py"]),
        (
            "capability_observability",
            [sys.executable, "scripts/check_capability_observability.py", "--self-test"],
        ),
        ("agent_guidance", [sys.executable, "scripts/check_agent_guidance.py", "--self-test"]),
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
        # This runs the suite once and asserts two things about the same result:
        # every test passed, and every test that skipped was declared in
        # data/allowed_test_skips.json with the CI job that runs it. A bare
        # `unittest discover` reports OK when a whole backend never executed.
        ("unittest", [sys.executable, "scripts/check_no_silent_skips.py", "--self-test"]),
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
        # Asserted against the artifact the run just produced, not only against
        # the self test: R116's rule is that a reader-visible criterion must
        # measure what the reader receives.
        (
            "demo_reference_list",
            [
                sys.executable,
                "scripts/check_reference_list_hygiene.py",
                "--report",
                "artifacts/ci_demo/report.md",
            ],
        ),
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
