"""Finance-domain governance for web candidates shown to readers."""

from __future__ import annotations

import re
from typing import Any


_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_FORECAST_RE = re.compile(r"forecast|prediction|预测|預測", re.IGNORECASE)
_REPORT_RE = re.compile(
    r"annual[-_\s]?report|full[-_\s]?year|financial[-_\s]?results|"
    r"20-?f|年报|年報|年度报告|年度報告|全年财报|全年財報",
    re.IGNORECASE,
)
_FILING_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?:1231)?x?20f", re.IGNORECASE)


def web_source_rejection_reason(
    source: Any,
    target_periods: tuple[str, ...],
) -> str | None:
    """Reject off-period annual-result and forecast identities without rewriting."""

    title = str(getattr(source, "title", ""))
    url = str(getattr(source, "url", ""))
    identity = f"{title} {url}"
    if _FORECAST_RE.search(identity):
        return "forecast_source"
    targets = {
        period[:4]
        for period in target_periods
        if re.fullmatch(r"20\d{2}.*", period)
    }
    if not targets:
        return None
    years = set(_YEAR_RE.findall(identity))
    years.update(_FILING_YEAR_RE.findall(identity))
    if years and years.isdisjoint(targets) and _REPORT_RE.search(identity):
        return "off_target_reporting_period"
    return None
