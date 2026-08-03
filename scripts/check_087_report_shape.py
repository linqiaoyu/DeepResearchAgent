"""Measure the reader-facing shape of a research package.

The probe deliberately evaluates the rendered report rather than provider or
citation plumbing: a green pipeline alone is not evidence of a useful report.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


AUDIT_HEADINGS = re.compile(
    r"^## (?:Agent 决策记录|数据获取降级|Live RAG cost reconciliation|Audit citation closure)$",
    re.MULTILINE,
)
DISCLAIMER = re.compile(r"(?:actual future results may be materially different|实际.*结果.*重大不同)", re.I)


def _section(text: str, title: str) -> str:
    match = re.search(rf"(?ms)^## {re.escape(title)}\s*$\n?(.*?)(?=^## |\Z)", text)
    return match.group(1) if match else ""


def measure(report: str) -> dict[str, int]:
    reader = report.split("## 参考来源", 1)[0]
    visible = [line for line in reader.splitlines() if line.strip()]
    boilerplate = sum(
        1
        for line in visible
        if not line.startswith("#")
        and not re.fullmatch(r"[| :\-]+", line)
        and len(line.strip()) <= 6
    )
    coverage = [line for line in _section(report, "指标覆盖状态").splitlines() if line.startswith("- ")]
    explained = sum(1 for line in coverage if any(word in line for word in ("无法", "缺失", "未取得", "不可得")))
    answered = len(coverage) - explained
    risks = _section(report, "风险与限制")
    assumptions = _section(report, "未验证假设")
    annual_outdated = sum(
        1
        for line in risks.splitlines()
        if "outdated_source" in line and any(
            token in line.lower()
            for token in ("20-f", "annual report", "年报", "sec edgar company facts")
        )
    )
    return {
        "reader_visible_lines": len(visible),
        "boilerplate_lines": boilerplate,
        "audit_sections_in_report": len(AUDIT_HEADINGS.findall(report)),
        "metrics_requested": len(coverage),
        "metrics_answered": answered,
        "metrics_explained_gap": explained,
        "derived_metrics_with_provenance": sum(
            1 for line in report.splitlines() if "推导值" in line and len(re.findall(r"\[\^\d+\]", line)) >= 2
        ),
        "analysis_false_positives": annual_outdated + len(DISCLAIMER.findall(assumptions)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    args = parser.parse_args()
    values = measure((args.package / "report.md").read_text(encoding="utf-8"))
    for key, value in values.items():
        print(f"{key}={value}")
    valid = (
        values["reader_visible_lines"] <= 40
        and values["boilerplate_lines"] == 0
        and values["audit_sections_in_report"] == 0
        and values["metrics_answered"] + values["metrics_explained_gap"] == values["metrics_requested"]
        and values["derived_metrics_with_provenance"] >= 1
        and values["analysis_false_positives"] == 0
    )
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
