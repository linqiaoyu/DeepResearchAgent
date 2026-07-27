from __future__ import annotations

# Finance SUT characterization contract; not a domain-generic evaluator.

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal


_NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_MEASURE_RE = re.compile(
    rf"(?P<number>{_NUMBER})\s*"
    r"(?P<unit>亿元|万元|个百分点|个百\s*分点|元|%|％|pct)",
    re.IGNORECASE,
)
_CITATION_RE = re.compile(r"\[\^(\d+)\]")
_NEGATIVE_RE = re.compile(r"下降|减少|下滑|降低|回落|收窄")
_POSITIVE_RE = re.compile(r"增长|增加|上升|提升|扩大")
_UNIT_MULTIPLIERS = {
    "元": Decimal("1"),
    "万元": Decimal("10000"),
    "亿元": Decimal("100000000"),
}


@dataclass(frozen=True, slots=True)
class ExpectedValue:
    name: Literal["current", "prior", "change"]
    value: Decimal
    kind: Literal["amount", "rate", "percentage_point"]


@dataclass(frozen=True, slots=True)
class MetricTruth:
    name: str
    line_pattern: str
    current: ExpectedValue
    prior: ExpectedValue | None
    change: ExpectedValue
    source_page: int

    @property
    def values(self) -> tuple[ExpectedValue, ...]:
        return tuple(
            item
            for item in (self.current, self.prior, self.change)
            if item is not None
        )


@dataclass(frozen=True, slots=True)
class GuardrailCase:
    slug: str
    topic: str
    metrics: tuple[MetricTruth, ...]


GUARDRAIL_CASES: tuple[GuardrailCase, ...] = (
    GuardrailCase(
        slug="moutai_600519",
        topic=(
            "贵州茅台（600519）2025 年营业收入、归母净利润与毛利率"
            "分别是多少？相较 2024 年的变化如何？"
        ),
        metrics=(
            MetricTruth(
                name="营业收入",
                line_pattern=r"营业收入|营收",
                current=ExpectedValue("current", Decimal("168838102514.79"), "amount"),
                prior=ExpectedValue("prior", Decimal("170899152276.34"), "amount"),
                change=ExpectedValue("change", Decimal("-1.21"), "rate"),
                source_page=6,
            ),
            MetricTruth(
                name="归母净利润",
                line_pattern=r"归母净利(?:润)?|归属于(?:上市公司|母公司)股东的净利润",
                current=ExpectedValue("current", Decimal("82320067101.68"), "amount"),
                prior=ExpectedValue("prior", Decimal("86228146421.62"), "amount"),
                change=ExpectedValue("change", Decimal("-4.53"), "rate"),
                source_page=6,
            ),
            MetricTruth(
                name="主营业务毛利率",
                line_pattern=r"主营业务毛利率|毛利率",
                current=ExpectedValue("current", Decimal("91.23"), "rate"),
                prior=None,
                change=ExpectedValue("change", Decimal("-0.78"), "percentage_point"),
                source_page=10,
            ),
        ),
    ),
    GuardrailCase(
        slug="hengrui_600276",
        topic=(
            "恒瑞医药（600276）2025 年营业收入、归母净利润与主营业务毛利率"
            "分别是多少？相较 2024 年的变化如何？"
        ),
        metrics=(
            MetricTruth(
                name="营业收入",
                line_pattern=r"营业收入|营收",
                current=ExpectedValue("current", Decimal("31629416193.83"), "amount"),
                prior=ExpectedValue("prior", Decimal("27984605342.06"), "amount"),
                change=ExpectedValue("change", Decimal("13.02"), "rate"),
                source_page=6,
            ),
            MetricTruth(
                name="归母净利润",
                line_pattern=r"归母净利(?:润)?|归属于(?:上市公司|母公司)股东的净利润",
                current=ExpectedValue("current", Decimal("7711054811.98"), "amount"),
                prior=ExpectedValue("prior", Decimal("6336527014.75"), "amount"),
                change=ExpectedValue("change", Decimal("21.69"), "rate"),
                source_page=6,
            ),
            MetricTruth(
                name="主营业务毛利率",
                line_pattern=r"主营业务毛利率|毛利率",
                current=ExpectedValue("current", Decimal("85.06"), "rate"),
                prior=None,
                change=ExpectedValue("change", Decimal("0.01"), "percentage_point"),
                source_page=58,
            ),
        ),
    ),
)


def guardrail_contract_sha256() -> str:
    """Identify the frozen questions, truths, and scorer contract."""

    payload = {
        "cases": [
            {
                "slug": case.slug,
                "topic": case.topic,
                "metrics": [
                    {
                        "name": metric.name,
                        "line_pattern": metric.line_pattern,
                        "values": [
                            {
                                "name": item.name,
                                "value": str(item.value),
                                "kind": item.kind,
                            }
                            for item in metric.values
                        ],
                        "source_page": metric.source_page,
                    }
                    for metric in case.metrics
                ],
            }
            for case in GUARDRAIL_CASES
        ],
        "scorer_version": "033-frozen-v1",
        "scope": "key_findings",
        "rounding": "half_display_step",
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def score_guardrail_report(
    report: str,
    case: GuardrailCase,
) -> dict[str, object]:
    key_findings = _section(report, "关键发现")
    metric_results: dict[str, object] = {}
    hallucinated = 0
    for metric in case.metrics:
        lines = [
            line.strip()
            for line in key_findings.splitlines()
            if line.strip().startswith("- ")
            and re.search(metric.line_pattern, line)
        ]
        line = lines[0] if lines else ""
        observations = _observations(line)
        value_results = {
            expected.name: any(
                _matches(observed, expected)
                for observed in observations
            )
            for expected in metric.values
        }
        cited = bool(_CITATION_RE.search(line))
        hallucinated_for_metric = sum(
            1
            for observed in observations
            if not any(
                _matches(observed, expected)
                for expected in metric.values
            )
        )
        hallucinated += hallucinated_for_metric
        metric_results[metric.name] = {
            "correct": bool(line) and cited and all(value_results.values()),
            "value_correctness": value_results,
            "cited": cited,
            "source_page_truth": metric.source_page,
            "hallucinated_number_count": hallucinated_for_metric,
            "observed_measures": [item.display for item in observations],
            "line": line,
        }
    correct_count = sum(
        int(bool(item["correct"]))
        for item in metric_results.values()
        if isinstance(item, dict)
    )
    return {
        "case": case.slug,
        "metric_correctness": metric_results,
        "correct_metrics": correct_count,
        "total_metrics": len(case.metrics),
        "hallucinated_number_count": hallucinated,
        "passed": correct_count == len(case.metrics) and hallucinated == 0,
    }


@dataclass(frozen=True, slots=True)
class _ObservedValue:
    value: Decimal
    kind: Literal["amount", "rate", "percentage_point"]
    display_step: Decimal
    display: str


def _observations(line: str) -> list[_ObservedValue]:
    observations: list[_ObservedValue] = []
    for match in _MEASURE_RE.finditer(line):
        raw_number = match.group("number")
        raw_unit = re.sub(r"\s+", "", match.group("unit")).lower()
        try:
            number = Decimal(raw_number.replace(",", ""))
        except InvalidOperation:
            continue
        if raw_unit in _UNIT_MULTIPLIERS:
            multiplier = _UNIT_MULTIPLIERS[raw_unit]
            kind: Literal["amount", "rate", "percentage_point"] = "amount"
        elif raw_unit in {"个百分点", "百分点", "pct"}:
            multiplier = Decimal("1")
            kind = "percentage_point"
        else:
            multiplier = Decimal("1")
            kind = "rate"
        if kind != "amount":
            direction = _direction(line, match.start("number"))
            if direction is not None:
                number = abs(number) * direction
        observations.append(
            _ObservedValue(
                value=number * multiplier,
                kind=kind,
                display_step=_display_step(raw_number) * multiplier,
                display=match.group(0),
            )
        )
    return observations


def _matches(observed: _ObservedValue, expected: ExpectedValue) -> bool:
    if observed.kind != expected.kind:
        return False
    return abs(observed.value - expected.value) <= observed.display_step / Decimal("2")


def _direction(text: str, number_start: int) -> Decimal | None:
    window = text[max(0, number_start - 32) : number_start]
    candidates: list[tuple[int, Decimal]] = []
    candidates.extend(
        (match.end(), Decimal("-1"))
        for match in _NEGATIVE_RE.finditer(window)
    )
    candidates.extend(
        (match.end(), Decimal("1"))
        for match in _POSITIVE_RE.finditer(window)
    )
    return max(candidates)[1] if candidates else None


def _display_step(number_text: str) -> Decimal:
    number = Decimal(number_text.replace(",", ""))
    return Decimal("1").scaleb(number.as_tuple().exponent)


def _section(report: str, heading: str) -> str:
    match = re.search(
        rf"(?ms)^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        report,
    )
    return match.group("body") if match else ""
