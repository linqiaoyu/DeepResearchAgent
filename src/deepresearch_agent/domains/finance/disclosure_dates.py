"""Resolve the date a US-listed filing actually became public.

A financial document has two dates that are easy to confuse and expensive to
conflate. ``effective_date`` is the end of the period it reports on; a FY2025
annual report carries 2025-12-31. ``filing_date`` is the day it was disclosed,
which for a 20-F is typically three to five months later. Point-in-time research
must use the second: a report filed in April 2026 was not knowable in January
2026, and treating the period end as the visibility date is textbook lookahead
bias.

R085 established this and backfilled the dates with a throwaway script that
wrote straight into one local SQLite file. R112 found the consequence: no ingest
path had ever written a ``filing_date``, the shipped corpus declared the day the
files were *downloaded* as their publication date, and retrieval had been
falling back to the period end throughout.

This is the provider that answers the question properly, for the registry that
publishes the authoritative answer. SEC EDGAR exposes a per-issuer submissions
index keyed by accession number, which is the same identifier embedded in every
archive URL, so a corpus of EDGAR URLs can be dated exactly rather than
estimated.

The service is public, free, and requires no key. It does require a
self-identifying User-Agent, and it rate-limits; both are handled here.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import httpx

from deepresearch_agent.tools import ToolErrorKind, ToolExecutionError

#: EDGAR archive URLs embed the issuer CIK and the 18-digit accession number,
#: which together identify one filing in the submissions index.
_ARCHIVE = re.compile(r"/data/(\d+)/(\d{18})/")
_ISO_DATE = re.compile(r"20\d{2}-\d{2}-\d{2}")

#: SEC asks automated clients to identify themselves and to stay under 10
#: requests per second. One request per issuer with a pause is far below that.
_USER_AGENT = "DeepResearchHarness/1.0 (research corpus builder; contact via repository)"
_MIN_REQUEST_INTERVAL_SECONDS = 0.2


@dataclass(frozen=True)
class DisclosureDate:
    """One filing's disclosure date, with the source that established it."""

    url: str
    filing_date: str
    source: str


class SecFilingDateProvider:
    """Fail-closed adapter over the SEC EDGAR submissions index.

    Bounded like every other external provider in this project: an explicit
    timeout, a capped attempt count, and a request budget. It never guesses. A
    URL it cannot resolve is reported as unresolved so the caller can degrade
    explicitly, rather than being handed a plausible-looking substitute.
    """

    fidelity = "real"
    source_name = "sec_edgar_submissions"

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        max_attempts: int = 3,
        max_requests: int = 200,
        client: httpx.Client | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.max_requests = max_requests
        self._client = client
        self._requests = 0
        self._last_request_at = 0.0

    @staticmethod
    def accession_key(url: str) -> tuple[str, str] | None:
        """Return the (cik, accession) an EDGAR archive URL identifies."""

        match = _ARCHIVE.search(url)
        return (match.group(1), match.group(2)) if match else None

    def _get(self, url: str) -> dict[str, object]:
        if self._requests >= self.max_requests:
            raise ToolExecutionError(
                ToolErrorKind.BUDGET_EXCEEDED,
                f"SEC request budget exhausted after {self.max_requests} requests",
            )
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < _MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(_MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        last: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                self._requests += 1
                self._last_request_at = time.monotonic()
                client = self._client or httpx
                response = client.get(
                    url,
                    headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 404:
                    raise ToolExecutionError(
                        ToolErrorKind.NOT_FOUND,
                        f"SEC submissions index has no entry: {url}",
                    )
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
            except ToolExecutionError:
                raise
            except Exception as error:  # noqa: BLE001 - re-raised as a tool error below.
                last = error
                if attempt == self.max_attempts:
                    break
                time.sleep(min(2.0 * attempt, 5.0))
        raise ToolExecutionError(
            ToolErrorKind.TRANSIENT,
            f"SEC submissions request failed after {self.max_attempts} attempts: {last}",
        )

    def _submissions(self, cik: str) -> dict[str, list[str]]:
        """Return accession -> filing date for one issuer, including history.

        The submissions document holds only the most recent filings inline and
        pushes older ones into separate files. A corpus that spans several years
        needs both, so the overflow files are followed.
        """

        payload = self._get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
        filings = payload.get("filings")
        blocks: list[dict[str, object]] = []
        if isinstance(filings, dict):
            recent = filings.get("recent")
            if isinstance(recent, dict):
                blocks.append(recent)
            extra = filings.get("files")
            if isinstance(extra, list):
                for entry in extra:
                    name = entry.get("name") if isinstance(entry, dict) else None
                    if isinstance(name, str) and name:
                        older = self._get(f"https://data.sec.gov/submissions/{name}")
                        if isinstance(older, dict):
                            blocks.append(older)
        resolved: dict[str, list[str]] = {}
        for block in blocks:
            accessions = block.get("accessionNumber")
            dates = block.get("filingDate")
            forms = block.get("form")
            if not isinstance(accessions, list) or not isinstance(dates, list):
                continue
            form_values = forms if isinstance(forms, list) else [""] * len(accessions)
            for accession, filed, form in zip(accessions, dates, form_values, strict=False):
                normalized = str(accession).replace("-", "")
                if _ISO_DATE.fullmatch(str(filed)):
                    resolved[normalized] = [str(filed), str(form)]
        return resolved

    def resolve(self, urls: list[str]) -> tuple[dict[str, DisclosureDate], dict[str, str]]:
        """Date every EDGAR URL it can, and name why each remaining one failed.

        Returns ``(resolved, unresolved)``. Nothing is invented for the second
        dictionary: a caller that cannot tolerate a gap must fail, not
        substitute.
        """

        by_cik: dict[str, set[str]] = {}
        unresolved: dict[str, str] = {}
        for url in urls:
            key = self.accession_key(url)
            if key is None:
                unresolved[url] = "url is not an SEC EDGAR archive path"
                continue
            by_cik.setdefault(key[0], set()).add(key[1])

        index: dict[tuple[str, str], str] = {}
        for cik in sorted(by_cik):
            try:
                submissions = self._submissions(cik)
            except ToolExecutionError as error:
                for url in urls:
                    key = self.accession_key(url)
                    if key and key[0] == cik:
                        unresolved[url] = f"submissions lookup failed: {error}"
                continue
            for accession, values in submissions.items():
                index[(cik, accession)] = values[0]

        resolved: dict[str, DisclosureDate] = {}
        for url in urls:
            if url in unresolved:
                continue
            key = self.accession_key(url)
            assert key is not None
            if key in index:
                resolved[url] = DisclosureDate(
                    url=url, filing_date=index[key], source=self.source_name
                )
            else:
                unresolved[url] = "accession not present in the issuer submissions index"
        return resolved, unresolved
