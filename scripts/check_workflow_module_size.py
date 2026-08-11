"""Enforce size bounds for workflow and RAG modules.

R125 changed two things about this guard.

It was wired into nothing -- not ``gate.py``, not a CI job -- and it was red:
``workflow/engine.py`` stood at 983 lines against its 900-line bound, and had
for an unknown number of rounds.  It is now in the gate, and the module was
split rather than the bound raised.

Its module list was also hand-maintained, which is the same class of defect the
guard exists to catch: a new module under ``workflow/`` or ``rag/`` was bounded
only if somebody remembered to add it here.  The two directories are now
discovered, so a new module is bounded the moment it lands.  Modules outside
them stay explicitly named, because widening the scope is a decision to review
rather than a side effect of a glob.
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_LINES = 600
ENGINE_MAX_LINES = 900
ENGINE = ROOT / "src/deepresearch_agent/workflow/engine.py"

#: Every module under these is bounded, including ones added after this line.
DISCOVERED_ROOTS = (
    ROOT / "src/deepresearch_agent/workflow",
    ROOT / "src/deepresearch_agent/rag",
)
#: Bounded modules outside the discovered roots.
NAMED_MODULES = (
    ROOT / "src/deepresearch_agent/orchestration/graph_runtime.py",
    ROOT / "src/deepresearch_agent/reporting/report_assembly.py",
)


def bounded_modules() -> tuple[Path, ...]:
    """Discovered modules plus named ones, excluding the engine's own bound."""

    found: set[Path] = set()
    for root in DISCOVERED_ROOTS:
        found.update(
            path
            for path in root.rglob("*.py")
            if path != ENGINE and path.name != "__init__.py"
        )
    found.update(NAMED_MODULES)
    return tuple(sorted(found))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("all", "engine", "extracted"), default="all")
    scope = parser.parse_args().scope
    violations: list[str] = []
    if scope in {"all", "engine"}:
        engine_lines = len(ENGINE.read_text(encoding="utf-8").splitlines())
        print(f"{ENGINE.relative_to(ROOT)}={engine_lines}")
        if engine_lines > ENGINE_MAX_LINES:
            violations.append(
                f"{ENGINE.relative_to(ROOT)} has {engine_lines} lines (max {ENGINE_MAX_LINES}). "
                "Extract a cohesive group of methods; raising the bound only moves the threshold."
            )
    if scope in {"all", "extracted"}:
        for path in bounded_modules():
            lines = len(path.read_text(encoding="utf-8").splitlines())
            relative = path.relative_to(ROOT)
            print(f"{relative}={lines}")
            if lines > MAX_LINES:
                violations.append(f"{relative} has {lines} lines (max {MAX_LINES})")
    if violations:
        raise SystemExit("\n".join(violations))


if __name__ == "__main__":
    main()
