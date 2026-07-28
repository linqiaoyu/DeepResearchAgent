"""Enforce the B2 upper bound for modules extracted from workflow.engine."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_LINES = 600
MODULES = (
    ROOT / "src/deepresearch_agent/orchestration/graph_runtime.py",
    ROOT / "src/deepresearch_agent/workflow/contracts.py",
    ROOT / "src/deepresearch_agent/workflow/graph_assembly.py",
    ROOT / "src/deepresearch_agent/workflow/helpers.py",
    ROOT / "src/deepresearch_agent/workflow/state.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/research.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/retry.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/research_loop.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/delivery.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/planning.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/quality.py",
    ROOT / "src/deepresearch_agent/reporting/report_assembly.py",
)


def main() -> None:
    violations: list[str] = []
    for path in MODULES:
        lines = len(path.read_text(encoding="utf-8").splitlines())
        relative = path.relative_to(ROOT)
        print(f"{relative}={lines}")
        if lines > MAX_LINES:
            violations.append(f"{relative} has {lines} lines (max {MAX_LINES})")
    if violations:
        raise SystemExit("\n".join(violations))


if __name__ == "__main__":
    main()
