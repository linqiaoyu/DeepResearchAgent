"""Print machine-readable round progress from versioned criteria definitions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CRITERIA_PATH = ROOT / "data/round/043_criteria.json"


def _criteria() -> list[dict[str, object]]:
    payload = json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("criteria must be a list")
    for item in payload:
        if not isinstance(item, dict) or not all(key in item for key in ("id", "block", "command", "target")):
            raise ValueError("each criterion needs id, block, command, and target")
        if not isinstance(item["command"], list) or not all(isinstance(part, str) for part in item["command"]):
            raise ValueError("criterion command must be a list of strings")
    return payload


def main() -> None:
    results: dict[str, list[bool]] = {}
    for criterion in _criteria():
        command = criterion["command"]
        assert isinstance(command, list)
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        output = (completed.stdout + completed.stderr).strip().replace("\n", " | ")
        passed = completed.returncode == 0
        if criterion["id"] == "B0-assets-tracked":
            passed = passed and len(completed.stdout.splitlines()) == 2
        print(
            f"{criterion['id']}: current={output or '<empty>'} target={criterion['target']} "
            f"{'PASS' if passed else 'FAIL'}"
        )
        block = criterion["block"]
        assert isinstance(block, str)
        results.setdefault(block, []).append(passed)
    closed = sorted(block for block, checks in results.items() if all(checks))
    open_blocks = sorted(block for block, checks in results.items() if not all(checks))
    print(f"closed_blocks={','.join(closed)} open_blocks={','.join(open_blocks)}")
    raise SystemExit(0 if not open_blocks else 1)


if __name__ == "__main__":
    main()
