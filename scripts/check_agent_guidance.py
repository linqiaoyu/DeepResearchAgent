from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BEGIN_MARKER = "<!-- BEGIN GENERATED SETTINGS DEFAULTS -->"
END_MARKER = "<!-- END GENERATED SETTINGS DEFAULTS -->"

REQUIRED_AGENTS_TEXT = (
    "## 3. 环境、安装、自检与本地门禁",
    ".venv/bin/python",
    'install -e ".[dev]"',
    "scripts/doctor.py",
    "PYTHONPATH=src",
    "scripts/gate.py",
    "完整本地 CI 的唯一标准入口",
    "运行产物",
    "replay_trajectory()",
    "在 LangGraph 图运行时之上自建 Agent 合同、预算与可观测层",
    "scripts/check_capability_graduation.py",
    "scripts/check_product_acceptance.py",
    "scripts/check_guard_wiring.py",
)
FORBIDDEN_CLAUDE_TEXT = (
    ".venv/bin/python",
    "scripts/gate.py",
    "PYTHONPATH=src",
    "scripts/doctor.py",
    "replay_trajectory()",
)


def _fail(message: str) -> None:
    print(f"agent_guidance_check=false: {message}", file=sys.stderr)
    raise SystemExit(1)


def _agents_structure_failures(agents: str) -> list[str]:
    failures: list[str] = []
    numbered = [int(value) for value in re.findall(r"^## (\d+)\.", agents, re.MULTILINE)]
    if numbered != list(range(1, 12)):
        failures.append(
            f"numbered sections must be exactly 1..11 in order, got {numbered}"
        )
    if "DeepResearchHarness 是自建 Agent Harness" in agents:
        failures.append(
            "AGENTS.md must not claim the graph runtime is self-built; LangGraph is the runtime"
        )
    if agents.count(BEGIN_MARKER) != 1:
        failures.append("generated Settings begin marker must occur exactly once")
    if agents.count(END_MARKER) != 1:
        failures.append("generated Settings end marker must occur exactly once")
    return failures


def _self_test(agents: str) -> None:
    cases = {
        "swapped_sections": agents.replace("## 10. 规则的执行面", "## 12. 规则的执行面"),
        "false_harness_claim": agents.replace(
            "DeepResearchHarness 是在 LangGraph 图运行时之上自建 Agent 合同、预算与可观测层的 harness",
            "DeepResearchHarness 是自建 Agent Harness",
        ),
    }
    for label, broken in cases.items():
        if not _agents_structure_failures(broken):
            _fail(f"self-test accepted mutation: {label}")
    print(f"agent_guidance_self_test=PASS cases={len(cases)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check shared AGENTS.md/CLAUDE.md guidance")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    claude = (project_root / "CLAUDE.md").read_text(encoding="utf-8")

    failures = _agents_structure_failures(agents)
    if failures:
        _fail("; ".join(failures))
    if args.self_test:
        _self_test(agents)

    if "@AGENTS.md" not in claude:
        _fail("CLAUDE.md must import AGENTS.md with Claude Code @ syntax")
    if "在分析、规划、修改代码或执行命令前，必须先读取并遵守" not in claude:
        _fail("CLAUDE.md must explicitly require reading AGENTS.md before work")
    if "以 `AGENTS.md` 为准" not in claude:
        _fail("CLAUDE.md must state AGENTS.md precedence")
    for text in REQUIRED_AGENTS_TEXT:
        if text not in agents:
            _fail(f"AGENTS.md is missing required shared guidance: {text}")
    for text in FORBIDDEN_CLAUDE_TEXT:
        if text in claude:
            _fail(f"CLAUDE.md must not duplicate shared guidance: {text}")
    if agents.count(BEGIN_MARKER) != 1 or agents.count(END_MARKER) != 1:
        _fail("AGENTS.md must retain exactly one generated Settings block")
    if agents.index(BEGIN_MARKER) >= agents.index(END_MARKER):
        _fail("AGENTS.md generated Settings markers are out of order")
    readme = (project_root / "README.md").read_text(encoding="utf-8")
    if re.search(r"Ran\s+\d+\s+tests", readme):
        _fail("README.md must not hard-code a test count; refer to CI instead")
    print("agent_guidance_check=true")


if __name__ == "__main__":
    main()
