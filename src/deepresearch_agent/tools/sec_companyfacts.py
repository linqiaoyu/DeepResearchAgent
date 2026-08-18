"""Bounded adapter for SEC EDGAR XBRL Company Facts data.

The SEC API is the primary structured source for a US-listed 20-F issuer.  It
is deliberately separate from the A-share AKShare adapter: an A-share symbol
must never be guessed as an EDGAR registrant, and an EDGAR issuer is never
sent to an A-share-wide symbol lookup.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

import httpx

from deepresearch_agent.domains.requirements import resolve_domain_capability
from deepresearch_agent.domains.protocols import StructuredDataDomain
from deepresearch_agent.schemas import StructuredDataRecord, SymbolInfo
from deepresearch_agent.tools.reliable_execution import RunToolContext


class SecCompanyFactsError(RuntimeError):
    """Raised when SEC EDGAR cannot return a bounded normalized payload."""


class StructuredDataUnsupportedMetric(SecCompanyFactsError):
    """Raised when SEC Company Facts has no domain mapping for a metric."""


_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"
_CIK_SYMBOL = re.compile(r"^CIK(?P<cik>\d{10})$", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")

class SecCompanyFactsProvider:
    """Read normalized annual XBRL facts for SEC registrants.

    ``symbol_resolve`` only accepts an exact ticker, CIK, registrant name, or
    an exact domain-expanded alias.  This protects against silently attaching
    facts to a similarly named issuer.  Every network call has a transport
    timeout and at most ``max_retries + 1`` attempts.
    """

    fidelity = "real"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        sleep_func: Callable[[float], None] = time.sleep,
        domain_pack: StructuredDataDomain | None = None,
        context: RunToolContext | None = None,
    ) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            headers={"User-Agent": "DeepResearchHarness/0.1 contact@example.invalid"},
            timeout=timeout_seconds,
        )
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._sleep = sleep_func
        self._domain_pack = resolve_domain_capability(
            domain_pack, consumer="SecCompanyFactsProvider"
        )
        self.context = context or RunToolContext.for_run()
        self._tickers: list[dict[str, object]] | None = None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def set_run_context(self, context: RunToolContext) -> None:
        """Bind this provider's counted egress to the current workflow run."""

        self.context = context

    @staticmethod
    def supports_request(capability: str) -> bool:
        """Declare the SEC filing-fact surface without fabricating prices."""

        return capability in {"symbol_resolve", "financial_indicators"}

    def symbol_resolve(self, company_name: str) -> SymbolInfo | None:
        query = company_name.strip()
        if not query:
            return None
        cik_match = _CIK_SYMBOL.fullmatch(query)
        if cik_match:
            return self._resolve_cik(int(cik_match.group("cik")))
        candidates = {query}
        aliases = getattr(self._domain_pack, "structured_issuer_aliases", None)
        if callable(aliases):
            resolved_aliases = aliases()
            if isinstance(resolved_aliases, Mapping):
                candidates.update(
                    english
                    for local_name, english in resolved_aliases.items()
                    if isinstance(local_name, str)
                    and isinstance(english, str)
                    and query in local_name
                )
        expanded = getattr(self._domain_pack, "expand_retrieval_query", None)
        if callable(expanded):
            rendered = expanded(query)
            if isinstance(rendered, str):
                candidates.add(rendered)
        matches: list[dict[str, object]] = []
        for item in self._company_tickers():
            title = str(item.get("title", ""))
            ticker = str(item.get("ticker", ""))
            normalized_title = _normalized_company_name(title)
            if any(
                normalized_title
                and (
                _normalized_company_name(candidate) == normalized_title
                or candidate.strip().casefold() == ticker.casefold()
                )
                for candidate in candidates
            ):
                matches.append(item)
        unique: dict[int, dict[str, object]] = {}
        for item in matches:
            if "cik_str" in item:
                unique.setdefault(int(item["cik_str"]), item)
        if len(unique) != 1:
            return None
        item = next(iter(unique.values()))
        return _symbol_info(item)

    def financial_indicators(
        self,
        symbol: str,
        periods: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> list[StructuredDataRecord]:
        cik_match = _CIK_SYMBOL.fullmatch(symbol.strip())
        info = self._resolve_cik(int(cik_match.group("cik"))) if cik_match else self.symbol_resolve(symbol)
        if info is None:
            return []
        cik = int(info.symbol.removeprefix("CIK"))
        payload = self._request_json(_COMPANY_FACTS_URL.format(cik=cik))
        facts = payload.get("facts", {})
        us_gaap = facts.get("us-gaap", {}) if isinstance(facts, dict) else {}
        metric_tags = self._domain_pack.structured_xbrl_concepts()
        wanted_metrics = tuple(metrics or metric_tags.keys())
        requested_periods = {_period_year(value) for value in (periods or [])}
        requested_periods.discard(None)
        records: list[StructuredDataRecord] = []
        seen: set[tuple[str, str, str]] = set()
        for requested_metric in wanted_metrics:
            canonical_metric = getattr(self._domain_pack, "canonical_metric", None)
            metric = (
                canonical_metric(requested_metric)
                if callable(canonical_metric)
                else requested_metric
            )
            tags = metric_tags.get(metric)
            if tags is None:
                unsupported = getattr(self._domain_pack, "unsupported_xbrl_metrics", None)
                if callable(unsupported) and metric in unsupported():
                    raise StructuredDataUnsupportedMetric(
                        f"SEC Company Facts does not support metric {requested_metric!r}"
                    )
                continue
            annual_facts = _select_tag_facts(us_gaap, tags, requested_periods)
            if not annual_facts:
                continue
            for unit, fact in annual_facts:
                end = str(fact["end"])
                key = (metric, end, unit)
                if key in seen:
                    continue
                seen.add(key)
                accession = str(fact["accn"]).replace("-", "")
                records.append(
                    StructuredDataRecord(
                        entity=info.entity,
                        symbol=info.symbol,
                        metric_name=metric,
                        period=end,
                        dimension="年度",
                        value=Decimal(str(fact["val"])),
                        unit=unit,
                        data_source="SEC EDGAR Company Facts",
                        as_of=date.today(),
                        source_pub_date=date.fromisoformat(str(fact["filed"])),
                        source_url=_ARCHIVE_URL.format(cik=cik, accession=accession),
                    )
                )
        return records

    def price_history(
        self, symbol: str, start_date: date, end_date: date
    ) -> list[StructuredDataRecord]:
        # Company Facts contains filing facts, not exchange price observations.
        # Callers consult ``supports_request`` before reaching this legacy
        # protocol method; retain this safe empty result for direct callers.
        del symbol, start_date, end_date
        return []

    def _resolve_cik(self, cik: int) -> SymbolInfo | None:
        matches = [item for item in self._company_tickers() if int(item.get("cik_str", -1)) == cik]
        # SEC can list multiple share-class tickers for one registrant.  The
        # CIK itself is already globally unique, so retain the catalog's first
        # ticker rather than treating a valid registrant as ambiguous.
        return _symbol_info(matches[0]) if matches else None

    def _company_tickers(self) -> list[dict[str, object]]:
        if self._tickers is None:
            payload = self._request_json(_COMPANY_TICKERS_URL)
            if not isinstance(payload, dict):
                raise SecCompanyFactsError("SEC company_tickers response must be an object")
            items = [item for item in payload.values() if isinstance(item, dict)]
            self._tickers = [dict(item) for item in items]
        return self._tickers

    def _request_json(self, url: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                self._consume_egress()
                response = self.client.get(url, timeout=self.timeout_seconds)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise SecCompanyFactsError("SEC response must be a JSON object")
                return payload
            except (httpx.HTTPError, ValueError, SecCompanyFactsError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self._sleep(2**attempt)
        raise SecCompanyFactsError(f"SEC request failed for {url}: {last_error}") from last_error

    def _consume_egress(self) -> None:
        self.context.consume_external_request("fetch", tool="sec_companyfacts")


def _normalized_company_name(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    ignored = {"inc", "incorporated", "limited", "ltd", "group", "holding", "holdings", "co", "company", "corporation"}
    return " ".join(token for token in tokens if token not in ignored)


def _symbol_info(item: Mapping[str, object]) -> SymbolInfo:
    cik = int(item["cik_str"])
    title = str(item["title"])
    ticker = str(item["ticker"])
    return SymbolInfo(
        entity=title,
        symbol=f"CIK{cik:010d}",
        exchange="SEC EDGAR",
        name=ticker,
        data_source="SEC company_tickers.json",
        as_of=date.today(),
    )


def _period_year(value: str) -> str | None:
    if re.fullmatch(r"20\d{6}", value):
        return value[:4]
    match = _YEAR.search(value)
    return match.group(1) if match else None


#: Two tags disagreeing by more than this on the same period and unit are not
#: two roundings of one disclosure; they are two different facts.
_CONFLICT_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class _TagCandidate:
    tag: str
    order: int
    facts: list[tuple[str, Mapping[str, Any]]]
    #: Reporting periods the request asked for that this tag answers.
    requested_coverage: int
    #: Annual periods the filer tags with this concept at all. A tag used for
    #: one year, while another mapped tag is used for every year, is not this
    #: filer's tag for the metric.
    filer_coverage: int

    @property
    def coverage(self) -> tuple[int, int]:
        """How well this tag answers the request. List order is not part of it."""

        return (self.requested_coverage, self.filer_coverage)


def _select_tag_facts(
    us_gaap: Mapping[str, Any],
    tags: tuple[str, ...],
    requested_years: set[str],
) -> list[tuple[str, Mapping[str, Any]]]:
    """Pick the tag this filer uses for the metric, not the first one listed.

    R098: the previous rule took the first mapped tag that returned anything.
    The domain vocabulary lists a generic revenue concept ahead of the specific
    one, and the R098 live filer tagged its total under the second while
    carrying a single unrelated 167,180,000 fact under the first. The reader
    received that number as the issuer's 2023 annual revenue, four lines above
    the same report's 55.6 billion, because a list position decided which of
    two mapped concepts was the metric.

    Coverage decides instead: the tag that answers more of the requested
    periods wins, then the tag the filer uses across more of its own annual
    periods, and only then list order.
    """

    candidates: list[_TagCandidate] = []
    for order, tag in enumerate(tags):
        concept = us_gaap.get(tag)
        if not isinstance(concept, dict):
            continue
        facts = _annual_facts(concept, requested_years)
        if not facts:
            continue
        candidates.append(
            _TagCandidate(
                tag=tag,
                order=order,
                facts=facts,
                requested_coverage=len({str(item["end"]) for _unit, item in facts}),
                filer_coverage=len(
                    {str(item["end"]) for _unit, item in _annual_facts(concept, set())}
                ),
            )
        )
    if not candidates:
        return []

    winner = max(candidates, key=lambda candidate: (candidate.coverage, -candidate.order))
    rivals = [
        candidate
        for candidate in candidates
        if candidate.tag != winner.tag and candidate.coverage == winner.coverage
    ]
    if not rivals:
        return winner.facts
    # Equally-used tags that disagree are an ambiguity Company Facts cannot
    # settle, and choosing by list position is what produced the wrong number
    # in the first place. Drop only the periods actually in conflict.
    conflicted = {
        (unit, str(item["end"]))
        for rival in rivals
        for unit, item in rival.facts
        for winner_unit, winner_item in winner.facts
        if winner_unit == unit
        and str(winner_item["end"]) == str(item["end"])
        and _materially_differs(winner_item["val"], item["val"])
    }
    return [
        (unit, item)
        for unit, item in winner.facts
        if (unit, str(item["end"])) not in conflicted
    ]


def _materially_differs(left: Any, right: Any) -> bool:
    try:
        first, second = Decimal(str(left)), Decimal(str(right))
    except (ArithmeticError, TypeError, ValueError):
        return str(left) != str(right)
    largest = max(abs(first), abs(second))
    if not largest:
        return False
    return abs(first - second) / largest > _CONFLICT_TOLERANCE


def _annual_facts(concept: Mapping[str, Any], requested_years: set[str]) -> list[tuple[str, Mapping[str, Any]]]:
    units = concept.get("units", {})
    if not isinstance(units, dict):
        return []
    selected: list[tuple[str, Mapping[str, Any]]] = []
    for unit, values in units.items():
        if not isinstance(unit, str) or not isinstance(values, list):
            continue
        facts = [
            item for item in values
            if isinstance(item, dict)
            and item.get("form") == "20-F"
            and item.get("fp") == "FY"
            and isinstance(item.get("fy"), int)
            and isinstance(item.get("end"), str)
            and isinstance(item.get("filed"), str)
            and isinstance(item.get("accn"), str)
            and "val" in item
            # ``fy`` identifies the filing and includes comparative facts from
            # earlier years.  The requested period selects the fact's own end.
            and (
                not requested_years
                or _period_year(str(item["end"])) in requested_years
            )
            and (not requested_years or str(item["fy"]) in requested_years)
        ]
        # A fact can recur in later filings. Keep the most recently filed
        # annual disclosure for each requested reporting-period endpoint.
        by_period: dict[str, Mapping[str, Any]] = {}
        for item in facts:
            end = str(item["end"])
            existing = by_period.get(end)
            if existing is None or str(item["filed"]) > str(existing["filed"]):
                by_period[end] = item
        selected.extend((unit, item) for item in by_period.values())
    # Company Facts may expose the same fact in reporting and translated
    # currencies. Emit one native-or-USD unit per metric/period; otherwise a
    # downstream numeric comparator would receive two competing values for one
    # disclosure fact.
    available = {unit for unit, _item in selected}
    preferred_unit = next(
        (unit for unit in ("CNY", "USD") if unit in available),
        min(available) if available else None,
    )
    return [item for item in selected if item[0] == preferred_unit]
