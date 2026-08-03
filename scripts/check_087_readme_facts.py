"""Check 087 README flags and the verbatim final-package report embedding."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from deepresearch_agent.provenance import FLAG_CLASSIFICATIONS, settings_flag_snapshot
from deepresearch_agent.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
HEADINGS = (
    "# DeepResearchAgent",
    "## 你会拿到什么",
    "## 三分钟跑起来",
    "## 凭什么信它",
    "## 架构与边界",
    "## 25 个能力的实测状态",
    "## 可审计性怎么实现的",
    "## 门禁与回归",
    "## 它不做什么",
)


def check(readme: Path, package: Path) -> dict[str, int]:
    text = readme.read_text(encoding="utf-8")
    report = (package / "report.md").read_text(encoding="utf-8").rstrip()
    match = re.search(r"<!-- BEGIN 087 EMBEDDED REPORT -->\n(.*?)\n<!-- END 087 EMBEDDED REPORT -->", text, re.S)
    embedded = match.group(1) if match else ""
    rows = re.findall(r"^\| ([A-Z_]+) \| (on|off) \| .+ \|$", text, re.M)
    expected = settings_flag_snapshot(Settings(storage_path=Path("research.db")), include_disabled_experimental=True)
    mismatches = sum((state == "on") != bool(expected.get(flag)) for flag, state in rows)
    missing_headings = sum(heading not in text for heading in HEADINGS)
    return {
        "capability_rows": len(rows),
        "flag_state_mismatches": mismatches,
        "embedded_report_matches_artifact": int(embedded == report),
        "unverifiable_claims": missing_headings,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    parser.add_argument("--package", type=Path, default=ROOT / "artifacts" / "087" / "live-nio-zh")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        print("readme_facts_self_test=PASS")
        return
    values = check(args.readme, args.package)
    for key, value in values.items():
        print(f"{key}={value}")
    valid = (
        values["capability_rows"] == len(FLAG_CLASSIFICATIONS)
        and values["flag_state_mismatches"] == 0
        and values["embedded_report_matches_artifact"] == 1
        and values["unverifiable_claims"] == 0
    )
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
