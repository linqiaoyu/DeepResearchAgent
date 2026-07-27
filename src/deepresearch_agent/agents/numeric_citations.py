from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Literal, Sequence

from deepresearch_agent.schemas import Evidence, NumericFields, StructuredDataRecord


NUMBER_PATTERN = (
    r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.\d+)?(?:[eE][+-]?\d+)?"
)
MEASURE_RE = re.compile(
    rf"(?P<number>{NUMBER_PATTERN})\s*"
    r"(?P<unit>百万元|千元|亿元|万元|亿元|亿|个百分点|个百\s*分点|元|%|％|pct)",
    re.IGNORECASE,
)
BARE_COMMA_AMOUNT_RE = re.compile(
    r"(?<![\d.])(?P<number>[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?)(?![\d])"
)
YOY_RE = re.compile(
    r"同比|(?:较|比)(?:上年|去年|(?:19|20)\d{2}年?)"
)
NEGATIVE_DIRECTION_RE = re.compile(r"下降|减少|下滑|降低|回落|收窄")
POSITIVE_DIRECTION_RE = re.compile(r"增长|增加|上升|提升|扩大")

BASE_METRIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "net_profit_parent",
        re.compile(r"归母净利(?:润)?|归属于(?:上市公司|母公司)股东的净利润"),
    ),
    (
        "gross_margin_main_business",
        re.compile(r"主营业务毛利率"),
    ),
    ("gross_margin", re.compile(r"(?<!主营业务)毛利率")),
    ("total_revenue", re.compile(r"营业总收入")),
    ("revenue", re.compile(r"(?<!总)营业收入|营收")),
    ("net_profit", re.compile(r"净利润|净利")),
    ("operating_cost", re.compile(r"营业成本")),
)

AMOUNT_MULTIPLIERS = {
    "元": Decimal("1"),
    "万元": Decimal("10000"),
    "亿元": Decimal("100000000"),
    "千元": Decimal("1000"),
    "百万元": Decimal("1000000"),
    "亿": Decimal("100000000"),
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
    *,
    required_metrics: set[str] | None = None,
) -> bool:
    """Return whether a financial number lacks support in the cited Evidence union."""

    claimed_values = _extract_text_values(claim_text)
    if required_metrics and "主营业务毛利率" in required_metrics:
        claimed_values = [
            replace(
                value,
                metric=(
                    "gross_margin_main_business:yoy"
                    if value.metric == "gross_margin:yoy"
                    else "gross_margin_main_business"
                ),
            )
            if value.metric in {
                "gross_margin",
                "gross_margin:yoy",
            }
            else value
            for value in claimed_values
        ]
    if not claimed_values:
        return False

    evidence_values: list[FinancialValue] = []
    for evidence in cited_evidence:
        extracted_values = _promote_main_business_margin_values(
            _extract_text_values(evidence.extract_text),
            evidence,
        )
        evidence_values.extend(extracted_values)
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
    evidence_values.extend(_derived_yoy_values(evidence_values))

    return any(not _value_is_supported(claimed, evidence_values) for claimed in claimed_values)


def _extract_text_values(text: str) -> list[FinancialValue]:
    values: list[FinancialValue] = []
    positions: list[int] = []
    occupied_spans: list[tuple[int, int]] = []

    for match in MEASURE_RE.finditer(text):
        occupied_spans.append(match.span())
        metric = _metric_before(text, match.start())
        if (
            not metric
            and _normalize_unit(match.group("unit"))
            == "个百分点"
            and re.search(
                r"毛利率比上年",
                text[max(0, match.start() - 300) : match.start()],
            )
        ):
            metric = "gross_margin:yoy"
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
            positions.append(match.start("number"))

    for match in BARE_COMMA_AMOUNT_RE.finditer(text):
        if any(_spans_overlap(match.span(), span) for span in occupied_spans):
            continue
        metric = _metric_before(text, match.start())
        if not metric:
            continue
        unit = _local_amount_unit(text, match.start()) or _default_amount_unit(text)
        value = _value_from_text(
            number_text=match.group("number"),
            unit_text=unit,
            metric=metric,
            text=text,
            number_start=match.start("number"),
        )
        if value:
            values.append(value)
            positions.append(match.start("number"))

    values = _assign_table_header_periods(
        text,
        values,
        positions,
    )
    return list(dict.fromkeys(values))


def _assign_table_header_periods(
    text: str,
    values: list[FinancialValue],
    positions: list[int],
) -> list[FinancialValue]:
    """Map ordered financial-statement columns to their ordered year headers."""
    grouped: dict[tuple[str, str], list[int]] = {}
    for index, value in enumerate(values):
        grouped.setdefault((value.kind, value.metric), []).append(index)
    updated = list(values)
    for indices in grouped.values():
        if len(indices) < 2:
            continue
        first_position = positions[indices[0]]
        header_periods = list(dict.fromkeys(
            match.group(1)
            for match in re.finditer(
                r"(?<!\d)((?:19|20)\d{2})(?!\d)",
                text[:first_position],
            )
        ))
        if len(header_periods) < len(indices):
            continue
        selected_periods = header_periods[-len(indices):]
        for index, period in zip(indices, selected_periods, strict=True):
            updated[index] = replace(updated[index], period=period)
    return updated


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
    if (
        metric == "gross_margin_main_business"
        and is_main_business_margin_dimension(fields.dimension)
        and (pattern is None or not pattern.search(extract_text))
    ):
        pattern = next(
            candidate
            for candidate_metric, candidate in BASE_METRIC_PATTERNS
            if candidate_metric == "gross_margin"
        )
    if pattern is None or not pattern.search(extract_text):
        return False
    expected = Decimal(str(fields.value))
    value_occurs_in_extract = False
    for match in re.finditer(NUMBER_PATTERN, extract_text):
        try:
            observed = Decimal(match.group(0).replace(",", ""))
        except InvalidOperation:
            continue
        tolerance = max(abs(expected), abs(observed)) * Decimal("1e-12")
        if abs(expected - observed) <= tolerance:
            value_occurs_in_extract = True
            break
    if not value_occurs_in_extract:
        return False

    # When the source excerpt exposes period-labelled statement columns, the
    # LLM-normalized period/value pair must agree with that source mapping.
    # Merely finding the value somewhere in the same two-column excerpt would
    # otherwise allow a 2024 value to be mislabeled as 2025.
    field_value = _value_from_numeric_fields(fields)
    if not field_value or not field_value.period:
        return True
    period_candidates = [
        candidate
        for candidate in _extract_text_values(extract_text)
        if candidate.kind == field_value.kind
        and _metrics_compatible(candidate.metric, field_value.metric)
        and candidate.period == field_value.period
    ]
    return not period_candidates or any(
        _values_match(field_value, candidate)
        for candidate in period_candidates
    )


def _promote_main_business_margin_values(
    values: list[FinancialValue],
    evidence: Evidence,
) -> list[FinancialValue]:
    """Scope generic margin values only when a typed total-row field anchors them."""
    typed_value = None
    dimension = None
    if evidence.structured_record:
        dimension = evidence.structured_record.dimension
        typed_value = _value_from_structured_record(
            evidence.structured_record
        )
    elif evidence.numeric_fields:
        dimension = evidence.numeric_fields.dimension
        if not is_main_business_margin_dimension(
            dimension
        ):
            return values
        typed_value = _value_from_numeric_fields(
            evidence.numeric_fields
        )
    if (
        typed_value is None
        or not typed_value.metric.startswith(
            "gross_margin_main_business"
        )
    ):
        return values

    values = [
        *values,
        *_main_business_margin_yoy_values(
            evidence.extract_text,
            dimension,
        ),
    ]
    promoted: list[FinancialValue] = []
    for value in values:
        metric = value.metric
        if (
            metric == "gross_margin"
            and not typed_value.metric.endswith(":yoy")
            and _values_match(
                replace(
                    value,
                    metric=typed_value.metric,
                ),
                typed_value,
            )
        ):
            metric = "gross_margin_main_business"
        elif metric == "gross_margin:yoy" and (
            typed_value.metric.endswith(":yoy")
            and _values_match(
                replace(
                    value,
                    metric=typed_value.metric,
                ),
                typed_value,
            )
        ):
            metric = "gross_margin_main_business:yoy"
        promoted.append(
            replace(value, metric=metric)
            if metric != value.metric
            else value
        )
    return promoted


def _main_business_margin_yoy_values(
    text: str,
    dimension: str | None,
) -> list[FinancialValue]:
    """Read percentage-point changes only from the anchored total row."""
    if not is_main_business_margin_dimension(dimension):
        return []
    values: list[FinancialValue] = []
    for match in MEASURE_RE.finditer(text):
        if _normalize_unit(match.group("unit")) != "个百分点":
            continue
        row_start = text.rfind("\n", 0, match.start()) + 1
        row = text[row_start : match.end()]
        if not _main_business_row_matches(row, dimension or ""):
            continue
        value = _value_from_text(
            number_text=match.group("number"),
            unit_text=match.group("unit"),
            metric="gross_margin_main_business:yoy",
            text=text,
            number_start=match.start("number"),
        )
        if value:
            values.append(value)
    return values


def _main_business_row_matches(
    row: str,
    dimension: str,
) -> bool:
    normalized_row = re.sub(r"\s+", "", row)
    normalized_dimension = re.sub(
        r"[\s：:/_-]+",
        "",
        dimension,
    )
    if any(
        term in normalized_row
        for term in (
            "茅台酒",
            "其他系列酒",
            "国内",
            "国外",
            "批发代理",
            "直销",
        )
    ):
        return False
    for label in ("酒类", "小计", "合计", "总计"):
        if label in normalized_dimension:
            return label in normalized_row
    industry_prefix = "主营业务分行业"
    if industry_prefix in normalized_dimension:
        row_label = normalized_dimension.split(
            industry_prefix,
            1,
        )[1]
        if row_label:
            return row_label in normalized_row
    return (
        "主营业务" in normalized_dimension
        and any(
            label in normalized_row
            for label in ("酒类", "小计", "合计", "总计")
        )
    )


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
    if (
        metric == "gross_margin"
        and is_main_business_margin_dimension(dimension)
    ):
        metric = "gross_margin_main_business"
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
            period=period or (
                _yoy_result_period(text, number_start)
                if metric.endswith(":yoy")
                else _period_before(text, number_start)
            ),
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
    yoy_matches = list(YOY_RE.finditer(window))
    if yoy_matches and yoy_matches[-1].end() >= metric_position:
        trailing = window[yoy_matches[-1].end() :]
        amount_at_number = re.match(
            rf"{NUMBER_PATTERN}\s*(?:百万元|千元|亿元|万元|亿|元)",
            text[number_start:],
        )
        if (
            amount_at_number
            and re.fullmatch(r"\s*的?\s*", trailing)
        ):
            # “较2024年的1,708.99亿元” names the comparison-base
            # amount. Only the later “下降1.21%” is the YoY result.
            return metric
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


def _yoy_result_period(
    text: str,
    number_start: int,
) -> str | None:
    """Bind a comparison rate to the subject year, not the `较2024年` base."""
    window = text[max(0, number_start - 180) : number_start]
    candidates: list[str] = []
    for match in re.finditer(r"(?:19|20)\d{2}", window):
        prefix = window[max(0, match.start() - 3) : match.start()]
        if re.search(r"较|比", prefix):
            continue
        candidates.append(match.group(0))
    return max(candidates) if candidates else None


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
    return Decimal("1").scaleb(number.as_tuple().exponent)


def _normalize_unit(unit_text: str) -> str | None:
    normalized = re.sub(r"\s+", "", unit_text).lower()
    if "百万元" in normalized:
        return "百万元"
    if "千元" in normalized:
        return "千元"
    if "亿元" in normalized:
        return "亿元"
    if "万元" in normalized:
        return "万元"
    if normalized == "亿":
        return "亿"
    if normalized == "元" or normalized.endswith("人民币元"):
        return "元"
    if "百分点" in normalized:
        return "个百分点"
    if normalized in {"%", "％"}:
        return "%"
    if normalized == "pct":
        return "pct"
    return None


def is_main_business_margin_dimension(dimension: str | None) -> bool:
    """Return whether a gross-margin row represents the main-business total."""
    if not dimension:
        return False
    normalized = re.sub(r"[\s：:（）()、，,/_-]", "", dimension)
    excluded = (
        "茅台酒",
        "其他系列酒",
        "国内",
        "国外",
        "批发代理",
        "直销",
        "销售渠道",
        "销售模式",
        "地区分部",
        "分地区",
        "分产品",
    )
    if any(term in normalized for term in excluded):
        return False
    return any(
        term in normalized
        for term in (
            "主营业务",
            "酒类",
            "小计",
            "合计",
            "总计",
        )
    )


def _local_amount_unit(text: str, position: int) -> str | None:
    """Return a unit only when declared in the current PDF/table neighbourhood."""
    start = max(0, text.rfind("[[PDF_PAGE=", 0, position), position - 1200)
    unit_match = list(re.finditer(
        r"(?:金额)?单位\s*[:：]\s*(?:人民币)?\s*(亿元|万元|元|千元|百万元|亿)",
        text[start:position],
    ))
    return unit_match[-1].group(1) if unit_match else None


def _default_amount_unit(text: str) -> str:
    unit_match = re.search(
        r"(?:金额)?单位\s*[:：]\s*(?:人民币)?\s*(百万元|千元|亿元|万元|亿|元)",
        text,
    )
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


def _derived_yoy_values(
    evidence_values: Sequence[FinancialValue],
) -> list[FinancialValue]:
    """Derive a cited year-on-year value from two source-backed periods."""
    grouped: dict[tuple[str, str], list[FinancialValue]] = {}
    for value in evidence_values:
        if value.metric.endswith(":yoy"):
            continue
        grouped.setdefault((value.kind, value.metric), []).append(value)

    derived: list[FinancialValue] = []
    for (kind, metric), raw_values in grouped.items():
        by_value: dict[Decimal, FinancialValue] = {}
        order: list[Decimal] = []
        for value in raw_values:
            existing = by_value.get(value.value)
            if existing is None:
                by_value[value.value] = value
                order.append(value.value)
            elif not existing.period and value.period:
                by_value[value.value] = value
        values = [by_value[value] for value in order]
        if len(values) < 2:
            continue
        period_values = [value for value in values if value.period]
        if len({value.period for value in period_values}) >= 2:
            ordered = sorted(
                period_values,
                key=lambda value: value.period or "",
                reverse=True,
            )
            current, prior = ordered[0], ordered[1]
        else:
            # Without typed periods there is no reliable current/prior order.
            continue
        if kind == "amount":
            if prior.value == 0:
                continue
            yoy = (
                current.value / prior.value - Decimal("1")
            ) * Decimal("100")
        else:
            yoy = current.value - prior.value
        derived.append(
            FinancialValue(
                kind="rate",
                metric=f"{metric}:yoy",
                period=current.period,
                value=yoy,
                display_step=Decimal("1e-12"),
            )
        )
    return derived


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
