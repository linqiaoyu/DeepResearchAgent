from __future__ import annotations

# Finance-domain implementation; generic extraction stays in agents.extractor.

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import NAMESPACE_URL, uuid5

from deepresearch_agent.agents.numeric_citations import (
    is_main_business_margin_dimension,
)
from deepresearch_agent.domains.registry import load_domain_pack
from deepresearch_agent.schemas import (
    Evidence,
    NumericFields,
    Source,
    SubQuestion,
)

_PDF_PAGE_RE = re.compile(r"\[\[PDF_PAGE=(\d+)\]\]")
_NUMBER = (
    r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
)
_RATE = r"[+-]?\d+(?:\.\d+)?"
_STATEMENT_LABELS = {
    "营业收入": r"营业收入",
    "归母净利润": (
        r"归属于(?:上市公司股东|母公司股东|母公司所有者)"
        r"的净利润"
    ),
}
_MARGIN_ROW_RE = re.compile(
    rf"(?m)^(?P<dimension>[^\n]+?)\s+"
    rf"(?P<revenue>{_NUMBER})\s+"
    rf"(?P<cost>{_NUMBER})\s+"
    rf"(?P<margin>{_RATE})\s+"
    rf"(?P<revenue_yoy>{_RATE})\s+"
    rf"(?P<cost_yoy>{_RATE})\s+"
    r"(?:(?P<direction>增加|减少|上升|下降)\s*)?"
    rf"(?P<margin_yoy>{_RATE})\s*"
    r"(?P<change_unit>个百\s*分点|个百分点)"
)
_PERIOD_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


@dataclass(frozen=True, slots=True)
class _PdfPage:
    number: int
    body: str
    body_offset: int


@dataclass(frozen=True, slots=True)
class _StatementRow:
    metric: str
    page: int
    extract_text: str
    extract_offset: int
    period_values: tuple[tuple[str, str], ...]
    current_period: str
    prior_period: str
    yoy: str
    unit: str


@dataclass(frozen=True, slots=True)
class _MarginRow:
    page: int
    extract_text: str
    extract_offset: int
    dimension: str
    current: str
    yoy: str
    direction: str


@dataclass(frozen=True, slots=True)
class AuthoritativeParseRejection:
    reason: str
    page: int | None = None
    matched_text: str | None = None


class FinanceTableExtractors:
    """Finance implementation of the domain table-extraction boundary."""

    def authoritative_backfills(
        self,
        research_id: str,
        sub_question: SubQuestion,
        sources: list[Source],
        *,
        rejections: list[AuthoritativeParseRejection],
    ) -> list[Evidence]:
        return authoritative_financial_backfills(
            research_id,
            sub_question,
            sources,
            rejections=rejections,
        )

    def merge_authoritative_evidence(
        self, evidence: list[Evidence], backfills: list[Evidence]
    ) -> list[Evidence]:
        return merge_authoritative_financial_evidence(evidence, backfills)


def authoritative_financial_backfills(
    research_id: str,
    sub_question: SubQuestion,
    sources: list[Source],
    *,
    rejections: list[AuthoritativeParseRejection] | None = None,
) -> list[Evidence]:
    """Backfill typed financial facts from verbatim primary annual-report rows.

    This parser is intentionally narrow. It does not replace the LLM
    extractor and does not normalize arbitrary prose. It only closes missing
    typed metric/period slots from a primary disclosure PDF when the source
    contains a statement row or an unambiguous main-business industry row.
    """
    requirements = _requirements(sub_question)
    if not requirements:
        return []
    evidence: list[Evidence] = []
    for source in sources:
        if not _eligible_annual_report(
            source,
            sub_question,
            requirements,
        ):
            continue
        pages = _pdf_pages(source.content)
        entity = _entity(sub_question, source)
        for metric in ("营业收入", "归母净利润"):
            periods = requirements.get(metric, [])
            if not periods:
                continue
            row = _find_statement_row(metric, pages, periods, rejections)
            if row is None:
                continue
            period_values = _period_values(periods, row)
            for period in periods:
                value = period_values.get(period)
                if value is None:
                    continue
                evidence.append(
                    _statement_evidence(
                        research_id=research_id,
                        sub_question=sub_question,
                        source=source,
                        entity=entity,
                        row=row,
                        period=period,
                        value=value,
                        is_current=(
                            period == row.current_period
                        ),
                    )
                )

        margin_periods = requirements.get(
            "主营业务毛利率",
            [],
        )
        current_period = max(margin_periods) if margin_periods else ""
        if current_period:
            row = _find_main_business_margin(
                pages,
                current_period,
                rejections,
            )
            if row is not None:
                evidence.append(
                    _margin_evidence(
                        research_id=research_id,
                        sub_question=sub_question,
                        source=source,
                        entity=entity,
                        row=row,
                        current_period=current_period,
                    )
                )
        if all(
            any(
                _evidence_slot(item) == (metric, period)
                for item in evidence
            )
            for metric, periods in requirements.items()
            if metric != "主营业务毛利率"
            for period in periods
        ) and (
            not margin_periods
            or any(
                _evidence_slot(item)
                == ("主营业务毛利率", current_period)
                for item in evidence
            )
        ):
            break
    return evidence


def merge_authoritative_financial_evidence(
    existing: list[Evidence],
    authoritative: list[Evidence],
) -> list[Evidence]:
    """Replace same-source LLM interpretations with parsed annual rows."""
    authoritative_slots = {
        (item.source_url, slot)
        for item in authoritative
        for slot in [_evidence_slot(item)]
        if slot is not None
    }
    retained = [
        item
        for item in existing
        if (
            item.source_kind == "structured"
            or (
                item.source_url,
                _evidence_slot(item),
            )
            not in authoritative_slots
        )
    ]
    return [*retained, *authoritative]


def _requirements(
    sub_question: SubQuestion,
) -> dict[str, list[str]]:
    requirements: dict[str, set[str]] = {}
    for request in sub_question.structured_data_requests:
        if request.capability != "financial_indicators":
            continue
        periods = {
            year
            for value in request.periods
            for year in [_period_year(str(value))]
            if year
        }
        for raw_metric in request.metrics:
            metric = _canonical_metric(raw_metric)
            if metric not in {
                "营业收入",
                "归母净利润",
                "主营业务毛利率",
            }:
                continue
            requirements.setdefault(metric, set()).update(periods)
    return {
        metric: sorted(periods)
        for metric, periods in requirements.items()
        if periods
    }


def _eligible_annual_report(
    source: Source,
    sub_question: SubQuestion,
    requirements: dict[str, list[str]],
) -> bool:
    if (
        source.source_tier != "primary"
        or source.source_type != "disclosure_pdf"
        or "年度报告" not in source.title
        or "摘要" in source.title
        or not _PDF_PAGE_RE.search(source.content)
    ):
        return False
    latest = max(
        period
        for periods in requirements.values()
        for period in periods
    )
    compact_title = re.sub(r"\s+", "", source.title)
    compact_prefix = re.sub(r"\s+", "", source.content[:500])
    if not (
        f"{latest}年年度报告" in compact_title
        or f"{latest}年年度报告" in compact_prefix
    ):
        return False
    company_names = {
        request.company_name
        for request in sub_question.structured_data_requests
        if request.capability == "financial_indicators"
        and request.company_name
    }
    return not company_names or any(
        re.sub(r"\s+", "", company_name)
        in f"{compact_title}\n{compact_prefix}"
        for company_name in company_names
    )


def _pdf_pages(content: str) -> list[_PdfPage]:
    markers = list(_PDF_PAGE_RE.finditer(content))
    pages: list[_PdfPage] = []
    for index, marker in enumerate(markers):
        body_offset = marker.end()
        body_end = (
            markers[index + 1].start()
            if index + 1 < len(markers)
            else len(content)
        )
        pages.append(
            _PdfPage(
                number=int(marker.group(1)),
                body=content[body_offset:body_end],
                body_offset=body_offset,
            )
        )
    return pages


def _find_statement_row(
    metric: str,
    pages: list[_PdfPage],
    periods: list[str],
    rejections: list[AuthoritativeParseRejection] | None = None,
) -> _StatementRow | None:
    label = _STATEMENT_LABELS[metric]
    pattern = re.compile(
        rf"(?m)^(?P<label>{label})\s+"
        rf"(?P<current>{_NUMBER})\s+"
        rf"(?P<prior>{_NUMBER})\s+"
        rf"(?P<yoy>{_RATE})\s+"
        rf"(?P<earlier>{_NUMBER})(?:\s|$)"
    )
    for page in pages:
        if "主要会计数据" not in page.body:
            continue
        match = pattern.search(page.body)
        if match is None:
            continue
        prefix = page.body[: match.start()]
        header_start = prefix.rfind("主要会计数据")
        if header_start < 0:
            continue
        header = prefix[header_start:]
        header_periods = tuple(
            dict.fromkeys(_PERIOD_RE.findall(header))
        )
        if (
            len(header_periods) != 3
            or header_periods[0] != max(periods)
        ):
            _reject(rejections, "unexpected_statement_header_periods", page, header[-160:])
            continue
        unit_info = _amount_unit(prefix)
        if unit_info is None:
            _reject(rejections, "unsupported_or_missing_amount_unit", page, prefix[-160:])
            continue
        unit, unit_offset = unit_info
        if not _yoy_matches(
            match.group("current"),
            match.group("prior"),
            match.group("yoy"),
        ):
            _reject(rejections, "statement_yoy_mismatch", page, match.group(0))
            continue
        extract_start = unit_offset
        return _StatementRow(
            metric=metric,
            page=page.number,
            extract_text=page.body[
                extract_start:match.end()
            ].rstrip(),
            extract_offset=page.body_offset + extract_start,
            period_values=tuple(
                zip(
                    header_periods,
                    (
                        match.group("current"),
                        match.group("prior"),
                        match.group("earlier"),
                    ),
                    strict=True,
                )
            ),
            current_period=header_periods[0],
            prior_period=header_periods[1],
            yoy=match.group("yoy"),
            unit=unit,
        )
    return None


def _find_main_business_margin(
    pages: list[_PdfPage],
    current_period: str,
    rejections: list[AuthoritativeParseRejection] | None = None,
) -> _MarginRow | None:
    for page in pages:
        start = page.body.find("主营业务分行业情况")
        if start < 0:
            continue
        end_candidates = [
            position
            for heading in (
                "主营业务分产品情况",
                "主营业务分地区情况",
                "主营业务分销售模式情况",
            )
            for position in [page.body.find(heading, start + 1)]
            if position >= 0
        ]
        end = min(end_candidates) if end_candidates else len(page.body)
        section = page.body[start:end]
        if (
            "毛利率" not in section
            or "单位" not in page.body[max(0, start - 300) : start]
            or not re.search(
                rf"(?<!\d){current_period}\s*年(?!\d)",
                page.body[:start],
            )
        ):
            continue
        matches = [
            match
            for match in _MARGIN_ROW_RE.finditer(section)
            if _margin_matches_arithmetic(match)
        ]
        if not matches:
            _reject(rejections, "main_business_margin_arithmetic_mismatch", page, section[-160:])
            continue
        totals = [
            match
            for match in matches
            if re.sub(r"\s+", "", match.group("dimension"))
            in {"小计", "合计", "总计"}
        ]
        selected = (
            totals[0]
            if len(totals) == 1
            else matches[0]
            if not totals and len(matches) == 1
            else None
        )
        if selected is None:
            _reject(rejections, "ambiguous_main_business_margin_row", page, section[-160:])
            continue
        raw_dimension = selected.group("dimension").strip()
        dimension = f"主营业务分行业：{raw_dimension}"
        if not is_main_business_margin_dimension(dimension):
            _reject(rejections, "unsupported_main_business_margin_dimension", page, raw_dimension)
            continue
        direction = _comparison_direction(
            selected.group("direction"),
            selected.group("margin_yoy"),
        )
        extract_start = max(0, page.body.rfind("单位", 0, start))
        extract_end = start + selected.end()
        return _MarginRow(
            page=page.number,
            extract_text=page.body[extract_start:extract_end].strip(),
            extract_offset=page.body_offset + extract_start,
            dimension=dimension,
            current=selected.group("margin"),
            yoy=selected.group("margin_yoy"),
            direction=direction,
        )
    return None


def _reject(
    rejections: list[AuthoritativeParseRejection] | None,
    reason: str,
    page: _PdfPage,
    matched_text: str,
) -> None:
    if rejections is not None:
        rejections.append(
            AuthoritativeParseRejection(
                reason=reason,
                page=page.number,
                matched_text=matched_text[:200],
            )
        )


def _period_values(
    periods: list[str],
    row: _StatementRow,
) -> dict[str, str]:
    if not periods:
        return {}
    available = dict(row.period_values)
    return {
        period: available[period]
        for period in periods
        if period in available
    }


def _statement_evidence(
    *,
    research_id: str,
    sub_question: SubQuestion,
    source: Source,
    entity: str,
    row: _StatementRow,
    period: str,
    value: str,
    is_current: bool,
) -> Evidence:
    comparison = ""
    if is_current:
        direction = _comparison_direction(None, row.yoy)
        comparison = (
            f"，较{row.prior_period}年{direction}"
            f"{_absolute_number(row.yoy)}%"
        )
    claim = (
        f"{period}年{row.metric}为{value}{row.unit}"
        f"{comparison}。"
    )
    return Evidence(
        id=str(
            uuid5(
                NAMESPACE_URL,
                (
                    f"{research_id}:{sub_question.id}:{source.url}:"
                    f"{row.metric}:{period}"
                ),
            )
        ),
        research_id=research_id,
        sub_question_id=sub_question.id,
        claim=claim,
        claim_type="data",
        source_url=source.url,
        source_title=source.title,
        source_pub_date=source.published_at,
        source_page=row.page,
        extract_text=row.extract_text,
        extract_offset_start=row.extract_offset,
        confidence=0.99,
        source_tier=source.source_tier,
        content_truncated=source.content_truncated,
        numeric_fields=NumericFields(
            entity=entity,
            metric_name=row.metric,
            period=f"{period}年",
            dimension="年度主要会计数据",
            value=_decimal(value),
            unit=row.unit,
        ),
    )


def _margin_evidence(
    *,
    research_id: str,
    sub_question: SubQuestion,
    source: Source,
    entity: str,
    row: _MarginRow,
    current_period: str,
) -> Evidence:
    comparison_period = str(int(current_period) - 1)
    claim = (
        f"{current_period}年主营业务毛利率为{row.current}%，"
        f"较{comparison_period}年{row.direction}"
        f"{_absolute_number(row.yoy)}个百分点。"
    )
    return Evidence(
        id=str(
            uuid5(
                NAMESPACE_URL,
                (
                    f"{research_id}:{sub_question.id}:{source.url}:"
                    f"主营业务毛利率:{current_period}"
                ),
            )
        ),
        research_id=research_id,
        sub_question_id=sub_question.id,
        claim=claim,
        claim_type="data",
        source_url=source.url,
        source_title=source.title,
        source_pub_date=source.published_at,
        source_page=row.page,
        extract_text=row.extract_text,
        extract_offset_start=row.extract_offset,
        confidence=0.99,
        source_tier=source.source_tier,
        content_truncated=source.content_truncated,
        numeric_fields=NumericFields(
            entity=entity,
            metric_name="主营业务毛利率",
            period=f"{current_period}年",
            dimension=row.dimension,
            value=_decimal(row.current),
            unit="%",
        ),
    )


def _amount_unit(
    prefix: str,
) -> tuple[str, int] | None:
    matches = list(
        re.finditer(
            r"单位\s*[:：]\s*(?:人民币)?\s*(亿元|百万元|万元|千元|元)",
            prefix,
        )
    )
    if not matches:
        return None
    match = matches[-1]
    return match.group(1), match.start()


def _comparison_direction(
    label: str | None,
    raw_value: str,
) -> str:
    if label in {"减少", "下降"}:
        return "下降"
    if label in {"增加", "上升"}:
        return "增长"
    return "下降" if raw_value.startswith(("-", "−")) else "增长"


def _absolute_number(value: str) -> str:
    return value.lstrip("+-−")


def _decimal(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _yoy_matches(
    current_text: str,
    prior_text: str,
    yoy_text: str,
) -> bool:
    current = _decimal(current_text)
    prior = _decimal(prior_text)
    disclosed = _decimal(yoy_text)
    if current is None or prior in {None, Decimal("0")}:
        return False
    if disclosed is None:
        return False
    computed = (
        (current / prior - Decimal("1"))
        * Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return computed == disclosed.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _margin_matches_arithmetic(
    match: re.Match[str],
) -> bool:
    revenue = _decimal(match.group("revenue"))
    cost = _decimal(match.group("cost"))
    disclosed = _decimal(match.group("margin"))
    disclosed_change = _decimal(match.group("margin_yoy"))
    if (
        match.group("direction")
        and disclosed_change is not None
        and disclosed_change < 0
    ):
        return False
    if revenue in {None, Decimal("0")} or cost is None:
        return False
    if disclosed is None:
        return False
    computed = (
        (revenue - cost) / revenue * Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return computed == disclosed.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def _entity(
    sub_question: SubQuestion,
    source: Source,
) -> str:
    for request in sub_question.structured_data_requests:
        if request.company_name:
            return request.company_name
    title = re.sub(
        r"\d{4}\s*年.*$",
        "",
        source.title,
    ).strip()
    return re.sub(r"^(?:关于|有关)", "", title).strip(" ：:")


def _canonical_metric(value: str | None) -> str:
    normalized = re.sub(
        r"[\s：:（）()]",
        "",
        value or "",
    )
    return load_domain_pack("finance").canonical_metric(normalized)


def _evidence_slot(
    evidence: Evidence,
) -> tuple[str, str] | None:
    record = evidence.structured_record
    fields = evidence.numeric_fields
    metric = _canonical_metric(
        record.metric_name
        if record
        else fields.metric_name
        if fields
        else None
    )
    period = _period_year(
        record.period
        if record
        else fields.period
        if fields
        else ""
    )
    if not metric or not period:
        return None
    return metric, period


def _period_year(value: str) -> str:
    rendered = value.strip()
    if re.fullmatch(r"(?:19|20)\d{6}", rendered):
        return rendered[:4]
    match = _PERIOD_RE.search(rendered)
    return match.group(1) if match else ""
