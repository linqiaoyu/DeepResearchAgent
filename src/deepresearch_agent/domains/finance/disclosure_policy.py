from __future__ import annotations

import re
from typing import Any


def is_full_annual_report_query(keyword: str) -> bool:
    return keyword == "年度报告"


def is_full_annual_report_title(title: str) -> bool:
    return bool(re.search(r"20\d{2}年年度报告$", title))


def report_year_from_title(title: str) -> int | None:
    match = re.search(r"(?<!\d)(20\d{2})年年度报告$", title.strip())
    return int(match.group(1)) if match else None


def is_amount_unit(value: str) -> bool:
    return value in {"元", "千元", "万元", "亿元", "美元", "股", "吨", "次", "倍", "%", "百分点"}


def is_historical_annual_disclosure(evidence: Any) -> bool:
    """Identify filings whose annual cadence makes news-age checks inapplicable."""

    source_title = str(getattr(evidence, "source_title", "")).lower()
    source_url = str(getattr(evidence, "source_url", "")).lower()
    return any(
        marker in f"{source_title} {source_url}"
        for marker in (
            "20-f",
            "20f",
            "annual report",
            "年度报告",
            "年报",
            "sec edgar company facts",
        )
    )


def reader_risk_visible(line: str) -> bool:
    """Keep real stale-news risks, but never surface a filing-age false positive."""

    if "outdated_source" not in line:
        return True
    return not any(
        marker in line.lower()
        for marker in ("20-f", "20f", "annual report", "年度报告", "年报")
    )


def reader_assumption_visible(line: str) -> bool:
    """Exclude boilerplate forward-looking legal language from analysis assumptions."""

    return not bool(
        re.search(
            r"actual future results may be materially different|"
            r"实际.*结果.*重大不同",
            line,
            re.IGNORECASE,
        )
    )


def is_legal_disclaimer_template(evidence: Any) -> bool:
    """Recognize a filing's standard forward-looking disclaimer, not a forecast."""

    text = " ".join(
        str(getattr(evidence, field, ""))
        for field in ("claim", "extract_text")
    )
    return not reader_assumption_visible(text)


def reader_metric_gap_explanation(metric: str) -> str:
    """Give a professional, finance-specific reason and follow-up path for gaps."""

    if metric in {"主营业务毛利率", "毛利率"}:
        return (
            "未在可用的结构化年报字段中找到该指标；可由利润表的营业收入与营业成本推算，"
            "本轮未作推算，推算值需二次核验后才可进入关键数据。"
        )
    return "未取得可引用的原始披露事实；可查阅对应年度报告或原始披露补充核验。"
