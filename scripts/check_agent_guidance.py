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


def main() -> None:
    parser = argparse.ArgumentParser(description="Check shared AGENTS.md/CLAUDE.md guidance")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    agents = (project_root / "AGENTS.md").read_text(encoding="utf-8")
    claude = (project_root / "CLAUDE.md").read_text(encoding="utf-8")

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
