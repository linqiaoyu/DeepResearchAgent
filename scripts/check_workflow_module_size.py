"""Enforce size bounds for workflow and RAG modules."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_LINES = 600
ENGINE_MAX_LINES = 900
ENGINE = ROOT / "src/deepresearch_agent/workflow/engine.py"
MODULES = (
    ROOT / "src/deepresearch_agent/orchestration/graph_runtime.py",
    ROOT / "src/deepresearch_agent/workflow/contracts.py",
    ROOT / "src/deepresearch_agent/workflow/graph_assembly.py",
    ROOT / "src/deepresearch_agent/workflow/helpers.py",
    ROOT / "src/deepresearch_agent/workflow/capability_setup.py",
    ROOT / "src/deepresearch_agent/workflow/state.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/research.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/retry.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/research_loop.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/delivery.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/planning.py",
    ROOT / "src/deepresearch_agent/workflow/nodes/quality.py",
    ROOT / "src/deepresearch_agent/reporting/report_assembly.py",
    ROOT / "src/deepresearch_agent/rag/__main__.py",
    ROOT / "src/deepresearch_agent/rag/chunking.py",
    ROOT / "src/deepresearch_agent/rag/evaluation.py",
    ROOT / "src/deepresearch_agent/rag/ingest.py",
    ROOT / "src/deepresearch_agent/rag/qdrant_index.py",
    ROOT / "src/deepresearch_agent/rag/retrieval.py",
    ROOT / "src/deepresearch_agent/rag/search.py",
)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("all", "engine", "extracted"), default="all")
    scope = parser.parse_args().scope
    violations: list[str] = []
    if scope in {"all", "engine"}:
        engine_lines = len(ENGINE.read_text(encoding="utf-8").splitlines())
        print(f"{ENGINE.relative_to(ROOT)}={engine_lines}")
        if engine_lines > ENGINE_MAX_LINES:
            violations.append(f"{ENGINE.relative_to(ROOT)} has {engine_lines} lines (max {ENGINE_MAX_LINES})")
    if scope in {"all", "extracted"}:
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
