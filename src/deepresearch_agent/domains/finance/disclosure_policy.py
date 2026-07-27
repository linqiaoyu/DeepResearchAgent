from __future__ import annotations

import re


def is_full_annual_report_query(keyword: str) -> bool:
    return keyword == "年度报告"


def is_full_annual_report_title(title: str) -> bool:
    return bool(re.search(r"20\d{2}年年度报告$", title))
