from __future__ import annotations

import re


def is_full_annual_report_query(keyword: str) -> bool:
    return keyword == "年度报告"


def is_full_annual_report_title(title: str) -> bool:
    return bool(re.search(r"20\d{2}年年度报告$", title))


def report_year_from_title(title: str) -> int | None:
    match = re.search(r"(?<!\d)(20\d{2})年年度报告$", title.strip())
    return int(match.group(1)) if match else None


def is_amount_unit(value: str) -> bool:
    return value in {"元", "千元", "万元", "亿元", "美元", "股", "吨", "次", "倍", "%", "百分点"}
