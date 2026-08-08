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
    # R095: this recognised a filing by tokens in its name, so NIO's HKEX annual
    # report -- served as `2025032100789_c.pdf` -- produced five reader-visible
    # stale-source warnings while this counter read zero. A filing venue in the
    # line is the same claim as a filing token.
    annual_outdated = sum(
        1
        for line in risks.splitlines()
        if "outdated_source" in line and any(
            token in line.lower()
            for token in (
                "20-f",
                "x20f",
                "annual report",
                "年报",
                "sec edgar company facts",
                "hkexnews",
                "sec.gov",
                "cninfo",
                "_c.pdf",
            )
        )
    )
    # A section that repeats one sentence is noise the reader has to wade
    # through, whatever produced it. R094 delivered the same warning five times.
    reader_bullets = [
        line.strip()
        for line in reader.splitlines()
        if line.strip().startswith("- ")
    ]
    duplicate_reader_lines = len(reader_bullets) - len(set(reader_bullets))
    analysis_false_positives = annual_outdated + len(DISCLAIMER.findall(assumptions))
    return {
        "reader_visible_lines": len(visible),
        "boilerplate_lines": boilerplate,
        # R090: the pass/fail criterion counts noise, not length. A cap on total
        # reader lines scored an empty report as the best possible one, and the
        # R087 A/B promoted capabilities on exactly that signal while both LLM
        # agents were silently truncated. Length is still reported, never judged.
        "duplicate_reader_lines": duplicate_reader_lines,
        "noise_lines": boilerplate + analysis_false_positives + duplicate_reader_lines,
        "audit_sections_in_report": len(AUDIT_HEADINGS.findall(report)),
        "metrics_requested": len(coverage),
        "metrics_answered": answered,
        "metrics_explained_gap": explained,
        "derived_metrics_with_provenance": sum(
            1 for line in report.splitlines() if "推导值" in line and len(re.findall(r"\[\^\d+\]", line)) >= 2
        ),
        "analysis_false_positives": analysis_false_positives,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        values = measure(
            "# report\n\n## 派生指标\n- 毛利率（推导值）：1 / 2 = 50% [^1] [^2]\n\n"
            "## 指标覆盖状态\n- 营业收入：1\n\n## 参考来源\n[^1]: source"
        )
        if values["derived_metrics_with_provenance"] != 1:
            raise SystemExit(1)
        noisy = measure(
            "# report\n\n## 未验证假设\n- actual future results may be materially different\n\n"
            "## 参考来源\n[^1]: source"
        )
        if noisy["noise_lines"] < 1:
            raise SystemExit(1)
        print("report_shape_self_test=PASS")
        return
    if args.package is None:
        parser.error("--package is required unless --self-test is used")
    values = measure((args.package / "report.md").read_text(encoding="utf-8"))
    for key, value in values.items():
        print(f"{key}={value}")
    valid = (
        values["noise_lines"] == 0
        and values["audit_sections_in_report"] == 0
        and values["metrics_answered"] + values["metrics_explained_gap"] == values["metrics_requested"]
        and (
            values["derived_metrics_with_provenance"] >= 1
            if args.package.name == "live-nio-zh"
            else True
        )
        and values["analysis_false_positives"] == 0
    )
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
