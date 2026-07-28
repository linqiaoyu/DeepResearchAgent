"""Print machine-readable round progress from versioned criteria definitions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CRITERIA_PATH = ROOT / "data/round/043_criteria.json"
BLOCKS_PATH = ROOT / "data/round/043_blocks.json"


def _criteria() -> list[dict[str, object]]:
    payload = json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("criteria must be a list")
    for item in payload:
        if not isinstance(item, dict) or not all(key in item for key in ("id", "block", "command")):
            raise ValueError("each criterion needs id, block, and command")
        if "display_target" in item and not isinstance(item["display_target"], str):
            raise ValueError("display_target must be a string")
        if "target" in item and not isinstance(item["target"], str):
            raise ValueError("legacy target must be a string")
        if "display_target" not in item and "target" not in item:
            raise ValueError("each criterion needs display_target")
        if not isinstance(item["command"], list) or not all(isinstance(part, str) for part in item["command"]):
            raise ValueError("criterion command must be a list of strings")
        if "expected_returncode" in item and not isinstance(item["expected_returncode"], int):
            raise ValueError("expected_returncode must be an int")
        if "expected_stdout" in item and not isinstance(item["expected_stdout"], str):
            raise ValueError("expected_stdout must be a string")
        if "machine_assertion" in item:
            assertion = item["machine_assertion"]
            if not isinstance(assertion, dict) or set(assertion) - {"returncode", "stdout"}:
                raise ValueError("machine_assertion has unknown fields")
            if "returncode" not in assertion:
                raise ValueError("machine_assertion requires returncode")
            if not isinstance(assertion["returncode"], int):
                raise ValueError("machine_assertion.returncode must be an int")
            if "stdout" in assertion and not isinstance(assertion["stdout"], str):
                raise ValueError("machine_assertion.stdout must be a string")
        if "kind" in item and item["kind"] != "artifact_presence":
            raise ValueError("criterion kind must be artifact_presence when present")
    return payload


def _declared_blocks() -> list[str]:
    payload = json.loads(BLOCKS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(
        isinstance(block, str) and block for block in payload
    ):
        raise ValueError("declared blocks must be a non-empty list of names")
    if len(set(payload)) != len(payload):
        raise ValueError("declared blocks must be unique")
    return payload


def main() -> None:
    declared_blocks = _declared_blocks()
    results: dict[str, list[bool]] = {block: [] for block in declared_blocks}
    behavior_seen: dict[str, bool] = {block: False for block in declared_blocks}
    for criterion in _criteria():
        command = criterion["command"]
        assert isinstance(command, list)
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        output = (completed.stdout + completed.stderr).strip().replace("\n", " | ")
        assertion = criterion.get("machine_assertion", {})
        assert isinstance(assertion, dict)
        expected_returncode = assertion.get(
            "returncode", criterion.get("expected_returncode", 0)
        )
        assert isinstance(expected_returncode, int)
        passed = completed.returncode == expected_returncode
        expected_stdout = assertion.get("stdout", criterion.get("expected_stdout"))
        if expected_stdout is not None:
            assert isinstance(expected_stdout, str)
            passed = passed and completed.stdout.strip() == expected_stdout
        if criterion["id"] == "B0-assets-tracked":
            passed = passed and len(completed.stdout.splitlines()) == 2
        kind = criterion.get("kind", "behavior")
        display_target = criterion.get("display_target", criterion.get("target"))
        assert isinstance(display_target, str)
        assertion_text = f"returncode={expected_returncode}"
        if expected_stdout is not None:
            assertion_text += ";stdout=exact"
        print(
            f"{criterion['id']}[{kind}]: current={output or '<empty>'} "
            f"display_target={display_target} assertion={assertion_text} "
            f"{'PASS' if passed else 'FAIL'}"
        )
        block = criterion["block"]
        assert isinstance(block, str)
        if block not in results:
            raise ValueError(f"criterion declares unknown block: {block}")
        results.setdefault(block, []).append(passed)
        if kind == "behavior":
            behavior_seen[block] = True
    missing_behavior = [block for block, seen in behavior_seen.items() if not seen]
    if missing_behavior:
        print("behavior_criteria_missing=" + ",".join(missing_behavior))
    closed = sorted(block for block, checks in results.items() if checks and all(checks))
    open_blocks = sorted(block for block, checks in results.items() if not checks or not all(checks))
    print(f"closed_blocks={','.join(closed)} open_blocks={','.join(open_blocks)}")
    raise SystemExit(0 if not open_blocks else 1)


if __name__ == "__main__":
    main()
