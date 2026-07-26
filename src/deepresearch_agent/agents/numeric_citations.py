from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Sequence

from deepresearch_agent.schemas import Evidence, NumericFields, StructuredDataRecord


NUMBER_PATTERN = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
MEASURE_RE = re.compile(
    rf"(?P<number>{NUMBER_PATTERN})\s*"
    r"(?P<unit>亿元|万元|个百分点|元|%|％|pct)",
    re.IGNORECASE,
)
BARE_COMMA_AMOUNT_RE = re.compile(
    r"(?<![\d.])(?P<number>[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?)(?![\d])"
)
YOY_RE = re.compile(r"同比|较上年|比上年|较去年|比去年")
NEGATIVE_DIRECTION_RE = re.compile(r"下降|减少|下滑|降低|回落|收窄")
POSITIVE_DIRECTION_RE = re.compile(r"增长|增加|上升|提升|扩大")

BASE_METRIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "net_profit_parent",
        re.compile(r"归母净利(?:润)?|归属于(?:上市公司|母公司)股东的净利润"),
    ),
    ("gross_margin", re.compile(r"毛利率")),
    ("revenue", re.compile(r"营业总收入|营业收入|营收")),
    ("net_profit", re.compile(r"净利润|净利")),
    ("operating_cost", re.compile(r"营业成本")),
)

AMOUNT_MULTIPLIERS = {
    "元": Decimal("1"),
    "万元": Decimal("10000"),
    "亿元": Decimal("100000000"),
}


@dataclass(frozen=True, slots=True)
class FinancialValue:
    kind: Literal["amount", "rate"]
    metric: str
    period: str | None
    value: Decimal
    display_step: Decimal


def has_financial_numeric_mismatch(
    claim_text: str,
    cited_evidence: Sequence[Evidence],
) -> bool:
    """Return whether a financial number lacks support in the cited Evidence union."""

    claimed_values = _extract_text_values(claim_text)
    if not claimed_values:
        return False

    evidence_values: list[FinancialValue] = []
    for evidence in cited_evidence:
        evidence_values.extend(_extract_text_values(evidence.extract_text))
        if evidence.structured_record:
            value = _value_from_structured_record(
                evidence.structured_record
            )
            if value:
                evidence_values.append(value)
        elif (
            evidence.numeric_fields
            and _numeric_fields_are_extract_grounded(
                evidence.numeric_fields,
                evidence.extract_text,
            )
        ):
            value = _value_from_numeric_fields(evidence.numeric_fields)
            if value:
                evidence_values.append(value)

    return any(not _value_is_supported(claimed, evidence_values) for claimed in claimed_values)


def _extract_text_values(text: str) -> list[FinancialValue]:
    values: list[FinancialValue] = []
    occupied_spans: list[tuple[int, int]] = []

    for match in MEASURE_RE.finditer(text):
        occupied_spans.append(match.span())
        metric = _metric_before(text, match.start())
        if not metric:
            continue
        value = _value_from_text(
            number_text=match.group("number"),
            unit_text=match.group("unit"),
            metric=metric,
            text=text,
            number_start=match.start("number"),
        )
        if value:
            values.append(value)

    default_amount_unit = _default_amount_unit(text)
    for match in BARE_COMMA_AMOUNT_RE.finditer(text):
        if any(_spans_overlap(match.span(), span) for span in occupied_spans):
            continue
        metric = _metric_before(text, match.start())
        if not metric:
            continue
        value = _value_from_text(
            number_text=match.group("number"),
            unit_text=default_amount_unit,
            metric=metric,
            text=text,
            number_start=match.start("number"),
        )
        if value:
            values.append(value)

    return list(dict.fromkeys(values))


def _numeric_fields_are_extract_grounded(
    fields: NumericFields,
    extract_text: str,
) -> bool:
    """Use LLM-normalized fields only when their metric and value occur in source.

    ``claim`` and ``numeric_fields`` are extractor outputs, not independent
    truth.  The fields may interpret table units, but they cannot introduce a
    number absent from the verbatim source excerpt.
    """
    if fields.value is None or not fields.metric_name:
        return False
    metric = _normalize_metric_name(fields.metric_name)
    if not metric:
        return False
    pattern = next(
        (
            candidate
            for candidate_metric, candidate in BASE_METRIC_PATTERNS
            if candidate_metric == metric
        ),
        None,
    )
    if pattern is None or not pattern.search(extract_text):
        return False
    expected = Decimal(str(fields.value))
    for match in re.finditer(NUMBER_PATTERN, extract_text):
        try:
            observed = Decimal(match.group(0).replace(",", ""))
        except InvalidOperation:
            continue
        tolerance = max(abs(expected), abs(observed)) * Decimal("1e-12")
        if abs(expected - observed) <= tolerance:
            return True
    return False


def _value_from_numeric_fields(fields: NumericFields) -> FinancialValue | None:
    if fields.value is None or not fields.metric_name or not fields.unit:
        return None
    return _value_from_structured_parts(
        metric_name=fields.metric_name,
        number_text=str(fields.value),
        unit_text=fields.unit,
        dimension=fields.dimension,
        period_text=fields.period,
    )


def _value_from_structured_record(record: StructuredDataRecord) -> FinancialValue | None:
    return _value_from_structured_parts(
        metric_name=record.metric_name,
        number_text=str(record.value),
        unit_text=record.unit,
        dimension=record.dimension,
        period_text=record.period,
    )


def _value_from_structured_parts(
    *,
    metric_name: str,
    number_text: str,
    unit_text: str,
    dimension: str,
    period_text: str | None,
) -> FinancialValue | None:
    metric = _normalize_metric_name(metric_name)
    unit = _normalize_unit(unit_text)
    if not metric or not unit:
        return None
    if YOY_RE.search(dimension):
        metric = f"{metric}:yoy"
    return _value_from_text(
        number_text=number_text,
        unit_text=unit,
        metric=metric,
        text="",
        number_start=0,
        period=_normalize_period(period_text),
    )


def _value_from_text(
    *,
    number_text: str,
    unit_text: str,
    metric: str,
    text: str,
    number_start: int,
    period: str | None = None,
) -> FinancialValue | None:
    try:
        number = Decimal(number_text.replace(",", ""))
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None

    unit = _normalize_unit(unit_text)
    if unit in AMOUNT_MULTIPLIERS:
        multiplier = AMOUNT_MULTIPLIERS[unit]
        return FinancialValue(
            kind="amount",
            metric=metric,
            period=period or _period_before(text, number_start),
            value=number * multiplier,
            display_step=_display_step(number_text) * multiplier,
        )
    if unit in {"%", "pct", "个百分点"}:
        direction = _direction_before(text, number_start)
        if direction:
            number = abs(number) * direction
        return FinancialValue(
            kind="rate",
            metric=metric,
            period=None,
            value=number,
            display_step=_display_step(number_text),
        )
    return None


def _metric_before(text: str, number_start: int) -> str | None:
    window_start = max(0, number_start - 120)
    window = text[window_start:number_start]
    last_boundary = max(window.rfind(boundary) for boundary in ("。", "；", ";", "\n"))
    if last_boundary >= 0:
        window = window[last_boundary + 1 :]
    metric_matches: list[tuple[int, str]] = []
    for metric, pattern in BASE_METRIC_PATTERNS:
        metric_matches.extend((match.end(), metric) for match in pattern.finditer(window))
    if not metric_matches:
        return None

    metric_position, metric = max(metric_matches)
    yoy_positions = [match.end() for match in YOY_RE.finditer(window)]
    if yoy_positions and max(yoy_positions) >= metric_position:
        return f"{metric}:yoy"
    return metric


def _normalize_metric_name(metric_name: str) -> str | None:
    matches: list[tuple[int, str]] = []
    for metric, pattern in BASE_METRIC_PATTERNS:
        matches.extend((match.end(), metric) for match in pattern.finditer(metric_name))
    return max(matches)[1] if matches else None


def _period_before(text: str, number_start: int) -> str | None:
    window = text[max(0, number_start - 28) : number_start]
    periods = re.findall(r"(?:19|20)\d{2}", window)
    return periods[-1] if periods else None


def _normalize_period(period_text: str | None) -> str | None:
    if not period_text:
        return None
    match = re.search(r"(?:19|20)\d{2}", period_text)
    return match.group(0) if match else None


def _direction_before(text: str, number_start: int) -> Decimal | None:
    window = text[max(0, number_start - 24) : number_start]
    directions: list[tuple[int, Decimal]] = []
    directions.extend((match.end(), Decimal("-1")) for match in NEGATIVE_DIRECTION_RE.finditer(window))
    directions.extend((match.end(), Decimal("1")) for match in POSITIVE_DIRECTION_RE.finditer(window))
    return max(directions)[1] if directions else None


def _display_step(number_text: str) -> Decimal:
    number = Decimal(number_text.replace(",", ""))
    return Decimal("1").scaleb(min(number.as_tuple().exponent, 0))


def _normalize_unit(unit_text: str) -> str | None:
    normalized = unit_text.strip().lower()
    if "亿元" in normalized:
        return "亿元"
    if "万元" in normalized:
        return "万元"
    if normalized == "元" or normalized.endswith("人民币元"):
        return "元"
    if "百分点" in normalized:
        return "个百分点"
    if normalized in {"%", "％"}:
        return "%"
    if normalized == "pct":
        return "pct"
    return None


def _default_amount_unit(text: str) -> str:
    unit_match = re.search(r"(?:金额)?单位\s*[:：]\s*(?:人民币)?\s*(亿元|万元|元)", text)
    return unit_match.group(1) if unit_match else "元"


def _value_is_supported(
    claimed: FinancialValue,
    evidence_values: Sequence[FinancialValue],
) -> bool:
    candidates = [
        supported
        for supported in evidence_values
        if claimed.kind == supported.kind
        and _metrics_compatible(claimed.metric, supported.metric)
    ]
    if claimed.period and any(candidate.period for candidate in candidates):
        candidates = [candidate for candidate in candidates if candidate.period == claimed.period]
    return any(_values_match(claimed, supported) for supported in candidates)


def _values_match(claimed: FinancialValue, supported: FinancialValue) -> bool:
    if claimed.kind != supported.kind or not _metrics_compatible(claimed.metric, supported.metric):
        return False
    if claimed.period and supported.period and claimed.period != supported.period:
        return False
    rounding_tolerance = max(claimed.display_step, supported.display_step) / Decimal("2")
    scale_tolerance = max(abs(claimed.value), abs(supported.value)) * Decimal("1e-12")
    return abs(claimed.value - supported.value) <= rounding_tolerance + scale_tolerance


def _metrics_compatible(claimed_metric: str, supported_metric: str) -> bool:
    if claimed_metric == supported_metric:
        return True
    return (
        claimed_metric == "yoy"
        and supported_metric.endswith(":yoy")
        or supported_metric == "yoy"
        and claimed_metric.endswith(":yoy")
    )


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]
