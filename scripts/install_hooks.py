"""Install the local guard against direct main-branch source commits."""

from __future__ import annotations

import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".git/hooks/pre-commit"
MARKER = "# deepresearch-agent-main-branch-guard"
HOOK_BODY = f"""#!/bin/sh
{MARKER}
branch=$(git branch --show-current)
if [ \"$branch\" = \"main\" ] && git diff --cached --name-only | grep -Eq '^(src|tests|scripts|data)/'; then
  echo 'Refusing a source/test/script/data commit directly on main. Create task/<round>-<name> first.' >&2
  exit 1
fi
"""


def main() -> None:
    existing = HOOK.read_text(encoding="utf-8") if HOOK.exists() else ""
    if existing and MARKER not in existing:
        raise SystemExit(f"refusing to overwrite unmanaged hook: {HOOK}")
    if existing != HOOK_BODY:
        HOOK.write_text(HOOK_BODY, encoding="utf-8")
        HOOK.chmod(HOOK.stat().st_mode | stat.S_IXUSR)
    print(f"installed_hook={HOOK.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
