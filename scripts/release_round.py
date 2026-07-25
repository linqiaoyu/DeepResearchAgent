from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from typing import Mapping, Sequence


FROZEN_PATHS = ("data/golden_set", "docs/evaluation.md")


@dataclass(frozen=True)
class ReleaseFailure(Exception):
    step: str
    returncode: int


def _run(
    step: str,
    command: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    print(f"[{step}] $ {' '.join(command)}")
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    if result.returncode:
        print(f"failed_step={step} returncode={result.returncode}", file=sys.stderr)
        raise ReleaseFailure(step=step, returncode=result.returncode)
    return result


def _require_clean_worktree() -> None:
    status = _run("worktree_status", ["git", "status", "--porcelain"])
    if status.stdout:
        print("failed_step=worktree_status reason=worktree_not_clean", file=sys.stderr)
        raise ReleaseFailure(step="worktree_status", returncode=1)
    print("worktree_clean=true")


def _require_main_branch() -> None:
    current = _run("current_branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if current.stdout.strip() != "main":
        print("failed_step=current_branch reason=branch_is_not_main", file=sys.stderr)
        raise ReleaseFailure(step="current_branch", returncode=1)
    print("current_branch=main")


def _merge_if_needed(branch: str, message: str) -> None:
    if branch == "main":
        print("failed_step=merge_state reason=release_branch_must_not_be_main", file=sys.stderr)
        raise ReleaseFailure(step="merge_state", returncode=1)
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", branch, "main"],
        check=False,
        capture_output=True,
        text=True,
    )
    if ancestor.returncode == 0:
        print("already_merged")
        return
    if ancestor.returncode != 1:
        if ancestor.stderr:
            print(ancestor.stderr, end="", file=sys.stderr)
        print(f"failed_step=merge_state returncode={ancestor.returncode}", file=sys.stderr)
        raise ReleaseFailure(step="merge_state", returncode=ancestor.returncode)
    _run("merge", ["git", "merge", "--no-ff", branch, "-m", message])


def _run_gates() -> None:
    _run("ci_gate", [sys.executable, "scripts/gate.py"])
    frozen = _run(
        "frozen_asset_diff",
        ["git", "diff", "--name-only", "origin/main..HEAD", "--", *FROZEN_PATHS],
    )
    if frozen.stdout:
        print("failed_step=frozen_asset_diff reason=frozen_assets_changed", file=sys.stderr)
        raise ReleaseFailure(step="frozen_asset_diff", returncode=1)
    print("frozen_asset_diff=empty")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge, verify, publish, and clean a release round.")
    parser.add_argument("--round", required=True, help="Round identifier, for example 019-e.")
    parser.add_argument("--branch", required=True, help="Local task branch to merge and delete with git branch -d.")
    parser.add_argument("--message", default="", help="Optional no-ff merge commit message when a merge is needed.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    message = args.message or f"merge: {args.round} release"
    try:
        _require_clean_worktree()
        _require_main_branch()
        _merge_if_needed(args.branch, message)
        _run_gates()
        _run("push", ["git", "push", "origin", "main"])
        _run("branch_cleanup", ["git", "branch", "-d", args.branch])
        sha = _run("main_sha", ["git", "rev-parse", "HEAD"])
        print(f"round={args.round}")
        print(f"main_sha={sha.stdout.strip()}")
    except ReleaseFailure as error:
        print(f"release_round_incomplete step={error.step}", file=sys.stderr)
        raise SystemExit(error.returncode) from error


if __name__ == "__main__":
    main()
