"""Deterministic reader-visible report contract and section-scoped probe."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
# R107: this pattern accepted only `http(s)`, and the gate only ever ran this
# checker against a sample whose sources are all SEC URLs. Pointed at a real
# delivered report for the first time, it reported `footnote_misrefs=2
# missing=['1', '2']` for two footnotes that were defined on the page -- their
# provider-origin URIs are `akshare://...`, which is what a structured record
# carries when the provider is an API rather than a document. A closure guard
# that cannot read half the citations this agent emits reports misses that are
# not there, and the run's own `audit_citation_closure=ok` disagreed with it.
_FOOTNOTE_DEF_RE = re.compile(
    r"^\[\^(\d+)\]:\s+.*?([a-z][a-z0-9+.\-]*://\S+)",
    re.MULTILINE,
)
_FOOTNOTE_REF_RE = re.compile(r"\[\^(\d+)\]")
_NUMBER_RE = re.compile(r"(?<!\d)(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?!\d)")


class ReaderContractError(AssertionError):
    pass


@dataclass(frozen=True)
class ExpectedFinding:
    metric: str
    rendered_value: str


def section(report: str, heading: str) -> str:
    """Return one exact level-two section; never fall back to full text."""

    matches = list(_HEADING_RE.finditer(report))
    selected = next(
        (index for index, match in enumerate(matches) if match.group(1) == heading),
        None,
    )
    if selected is None:
        raise ReaderContractError(f"missing_section={heading}")
    start = matches[selected].end()
    end = matches[selected + 1].start() if selected + 1 < len(matches) else len(report)
    return report[start:end]


def validate_expected_findings(
    report: str,
    expected: tuple[ExpectedFinding, ...],
    *,
    forbid_gap: bool = True,
) -> None:
    key_findings = section(report, "关键发现")
    for finding in expected:
        if finding.metric not in key_findings:
            raise ReaderContractError(f"key_findings_missing_metric={finding.metric}")
        if finding.rendered_value not in key_findings:
            raise ReaderContractError(
                f"key_findings_missing_value={finding.metric}:{finding.rendered_value}"
            )
        _validate_amount_rendering(finding)
    if forbid_gap and "未取得" in key_findings:
        raise ReaderContractError("key_findings_contains_unavailable_gap")


def validate_self_consistency(report: str, metrics: tuple[str, ...]) -> None:
    key_findings = section(report, "关键发现")
    for metric in metrics:
        metric_number = re.compile(
            rf"{re.escape(metric)}[^\n]{{0,160}}{_NUMBER_RE.pattern}"
        )
        numeric_anywhere = bool(metric_number.search(report))
        gap_in_findings = bool(
            re.search(rf"{re.escape(metric)}[^\n]*未取得", key_findings)
        )
        if numeric_anywhere and gap_in_findings:
            raise ReaderContractError(
                f"self_contradiction_numeric_value_and_gap={metric}"
            )


def validate_footnotes(report: str) -> None:
    definitions = _FOOTNOTE_DEF_RE.findall(report)
    numbers = [number for number, _url in definitions]
    urls = [url.rstrip(".,)") for _number, url in definitions]
    if len(urls) != len(set(urls)):
        raise ReaderContractError("duplicate_source_url_footnotes")
    defined = set(numbers)
    body = report.split("## 参考来源", 1)[0]
    referenced = set(_FOOTNOTE_REF_RE.findall(body))
    missing = sorted(referenced - defined)
    if missing:
        raise ReaderContractError(f"footnote_misrefs={len(missing)} missing={missing}")


def validate_degradation_notice(report: str, *, degradation_expected: bool) -> None:
    if degradation_expected and "## 数据获取降级" not in report:
        raise ReaderContractError("silent_degradation_notice_missing")


def validate_exact_amounts(
    report: str,
    expected: tuple[ExpectedFinding, ...],
) -> None:
    key_findings = section(report, "关键发现")
    for finding in expected:
        expected_match = _NUMBER_RE.search(finding.rendered_value)
        # R108: a rate is written tight to its percent sign, an amount is
        # spaced from its currency unit. Reading only the second form made this
        # check blind to every margin the report delivers.
        observed_match = re.search(
            rf"{re.escape(finding.metric)}[^\n]{{0,180}}?{_NUMBER_RE.pattern}"
            r"(?:\s*%|\s+(?:CNY|RMB|元|万元|亿元))",
            key_findings,
        )
        if not expected_match or not observed_match:
            raise ReaderContractError(f"amount_not_observed={finding.metric}")
        expected_value = Decimal(expected_match.group(1).replace(",", ""))
        observed_value = Decimal(observed_match.group(1).replace(",", ""))
        if observed_value != expected_value:
            raise ReaderContractError(
                f"magnitude_mismatch={finding.metric}:"
                f"expected={expected_value}:observed={observed_value}"
            )


def _validate_amount_rendering(finding: ExpectedFinding) -> None:
    # R108: this required whitespace before every unit. R107 delivered only
    # amounts, so the rule was never applied to a rate -- and the first
    # delivered 毛利率 made it demand `19.438342 %`, which is not how a
    # percentage is written. A currency unit takes its space; a percent sign
    # does not.
    match = re.fullmatch(
        r"(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
        r"(?:\s*(%)|\s+([A-Za-z]+|元|万元|亿元))",
        finding.rendered_value,
    )
    if not match:
        raise ReaderContractError(
            f"invalid_grouping_or_unit_spacing={finding.metric}:{finding.rendered_value}"
        )
    try:
        value = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation as exc:
        raise ReaderContractError(f"invalid_decimal={finding.metric}") from exc
    if abs(value) >= 1000 and "," not in match.group(1):
        raise ReaderContractError(f"missing_thousands_grouping={finding.metric}")


def _sample_report(mutation: str | None = None) -> tuple[str, tuple[ExpectedFinding, ...]]:
    revenue = "65,731,559,000 CNY"
    gross = "6,492,762,000 CNY"
    margin = "19.44%"
    key_lines = [
        f"- 营业收入：NIO Inc. 2024年年度营业收入为{revenue}。 [^1]",
        f"- 毛利：NIO Inc. 2024年年度毛利为{gross}。 [^2]",
        f"- 毛利率：NIO Inc. 2024年年度毛利率为{margin}。 [^2]",
    ]
    definitions = [
        "[^1]: SEC Company Facts. https://www.sec.gov/companyfacts/1736541",
        # A structured record from an API provider cites a provider-origin URI,
        # not a document URL. The sample carries one so this checker is never
        # again validated only against citations it happens to find readable.
        "[^2]: AKShare: stock_financial_abstract. akshare://毛利/1736541/20241231",
    ]
    degradation = [
        "## 数据获取降级",
        "- web_source_governance / permanent: rejected forecast source (attempts=1)",
    ]
    expected_revenue = revenue
    if mutation == "c1":
        key_lines = key_lines[1:]
    elif mutation == "c2":
        key_lines[0] = "- 营业收入：未取得满足保真合同的事实。"
    elif mutation == "c3":
        definitions.append(
            "[^3]: Duplicate SEC fact. https://www.sec.gov/companyfacts/1736541"
        )
    elif mutation == "c4":
        key_lines[0] = key_lines[0].replace(revenue, "6,573,155,900 CNY")
    elif mutation == "c5":
        degradation = []
    report = "\n".join(
        [
            "# Offline contract",
            "",
            "## 关键发现",
            "",
            *key_lines,
            "",
            "## 详细分析",
            f"- 营业收入为{revenue}。 [^1]",
            f"- 毛利为{gross}。 [^2]",
            "",
            "## 参考来源",
            *definitions,
            "",
            *degradation,
        ]
    )
    return report, (
        ExpectedFinding("营业收入", expected_revenue),
        ExpectedFinding("毛利", gross),
        ExpectedFinding("毛利率", margin),
    )


def validate_sample(report: str, expected: tuple[ExpectedFinding, ...]) -> None:
    validate_expected_findings(report, expected)
    validate_exact_amounts(report, expected)
    validate_self_consistency(report, tuple(item.metric for item in expected))
    validate_footnotes(report)
    validate_degradation_notice(report, degradation_expected=True)


def _parse_expected(values: list[str]) -> tuple[ExpectedFinding, ...]:
    parsed: list[ExpectedFinding] = []
    for value in values:
        if "=" not in value:
            raise ReaderContractError(f"invalid_expectation={value}")
        metric, rendered = value.split("=", 1)
        parsed.append(ExpectedFinding(metric.strip(), rendered.strip()))
    return tuple(parsed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--mutation", choices=("c1", "c2", "c3", "c4", "c5"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--expect", action="append", default=[])
    parser.add_argument("--forbid-gap", action="store_true")
    args = parser.parse_args()
    try:
        if args.mutation:
            report, expected = _sample_report(args.mutation)
            if args.mutation == "c1":
                validate_expected_findings(report, expected)
            elif args.mutation == "c2":
                validate_self_consistency(report, ("营业收入", "毛利"))
            elif args.mutation == "c3":
                validate_footnotes(report)
            elif args.mutation == "c4":
                validate_exact_amounts(report, expected)
            else:
                validate_degradation_notice(report, degradation_expected=True)
        elif args.self_test:
            report, expected = _sample_report()
            validate_sample(report, expected)
        elif args.report:
            report = args.report.read_text(encoding="utf-8")
            expected = _parse_expected(args.expect)
            validate_expected_findings(
                report,
                expected,
                forbid_gap=args.forbid_gap,
            )
            validate_self_consistency(
                report,
                tuple(item.metric for item in expected),
            )
            validate_footnotes(report)
        else:
            parser.error("choose --self-test, --mutation, or --report")
    except ReaderContractError as exc:
        print(f"reader_visible_contract=FAIL {exc}", file=sys.stderr)
        return 1
    print("reader_visible_contract=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
