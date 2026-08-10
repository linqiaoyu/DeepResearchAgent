"""The provider that answers when a filing became public.

R112 replaced a substituted disclosure date with a resolved one. These tests pin
the two behaviours that make the substitution impossible to reintroduce
accidentally: the provider reads the registry's own answer, and it reports what
it could not resolve instead of inventing a plausible date.

No network. A stub client stands in for SEC EDGAR.
"""

from __future__ import annotations

import unittest

from deepresearch_agent.domains.finance.disclosure_dates import SecFilingDateProvider
from deepresearch_agent.tools import ToolErrorKind, ToolExecutionError

_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/report.htm"


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self) -> object:
        return self._payload


class _StubClient:
    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.requests: list[str] = []

    def get(self, url: str, **_kwargs: object) -> _Response:
        self.requests.append(url)
        if url not in self.routes:
            return _Response({}, status_code=404)
        return _Response(self.routes[url])


def _submissions(rows: list[tuple[str, str, str]], files: list[str] | None = None) -> dict:
    return {
        "filings": {
            "recent": {
                "accessionNumber": [row[0] for row in rows],
                "filingDate": [row[1] for row in rows],
                "form": [row[2] for row in rows],
            },
            "files": [{"name": name} for name in (files or [])],
        }
    }


class SecFilingDateProviderTests(unittest.TestCase):
    def test_it_returns_the_registry_date_not_the_period_end(self) -> None:
        url = _ARCHIVE.format(cik="1577552", accession="000110465922082622")
        client = _StubClient(
            {
                "https://data.sec.gov/submissions/CIK0001577552.json": _submissions(
                    [("0001104659-22-082622", "2022-07-26", "20-F")]
                )
            }
        )
        provider = SecFilingDateProvider(client=client)

        resolved, unresolved = provider.resolve([url])

        self.assertEqual(unresolved, {})
        self.assertEqual(resolved[url].filing_date, "2022-07-26")
        self.assertEqual(resolved[url].source, "sec_edgar_submissions")

    def test_it_follows_the_overflow_files_for_older_filings(self) -> None:
        # The submissions document holds only recent filings inline. A corpus
        # spanning several years needs the overflow, and missing it would look
        # exactly like an unresolvable accession.
        url = _ARCHIVE.format(cik="1", accession="000000000000000001")
        client = _StubClient(
            {
                "https://data.sec.gov/submissions/CIK0000000001.json": _submissions(
                    [("0009999999-99-999999", "2025-01-01", "20-F")],
                    files=["CIK0000000001-submissions-001.json"],
                ),
                "https://data.sec.gov/submissions/CIK0000000001-submissions-001.json": {
                    "accessionNumber": ["0000000000-00-000001"],
                    "filingDate": ["2019-04-30"],
                    "form": ["20-F"],
                },
            }
        )
        provider = SecFilingDateProvider(client=client)

        resolved, unresolved = provider.resolve([url])

        self.assertEqual(unresolved, {})
        self.assertEqual(resolved[url].filing_date, "2019-04-30")

    def test_an_unknown_accession_is_reported_not_invented(self) -> None:
        url = _ARCHIVE.format(cik="1", accession="000000000000000042")
        client = _StubClient(
            {
                "https://data.sec.gov/submissions/CIK0000000001.json": _submissions(
                    [("0000000000-00-000001", "2019-04-30", "20-F")]
                )
            }
        )
        provider = SecFilingDateProvider(client=client)

        resolved, unresolved = provider.resolve([url])

        self.assertEqual(resolved, {})
        self.assertIn("accession not present", unresolved[url])

    def test_a_non_edgar_url_is_reported_without_a_request(self) -> None:
        client = _StubClient({})
        provider = SecFilingDateProvider(client=client)

        resolved, unresolved = provider.resolve(["https://example.test/not-edgar.pdf"])

        self.assertEqual(resolved, {})
        self.assertIn("not an SEC EDGAR archive path", unresolved["https://example.test/not-edgar.pdf"])
        self.assertEqual(client.requests, [])

    def test_a_lookup_failure_degrades_explicitly(self) -> None:
        url = _ARCHIVE.format(cik="7", accession="000000000000000007")
        provider = SecFilingDateProvider(client=_StubClient({}), max_attempts=1)

        resolved, unresolved = provider.resolve([url])

        self.assertEqual(resolved, {})
        self.assertIn("submissions lookup failed", unresolved[url])

    def test_it_refuses_to_exceed_its_request_budget(self) -> None:
        client = _StubClient({})
        provider = SecFilingDateProvider(client=client, max_requests=0)

        with self.assertRaises(ToolExecutionError) as caught:
            provider._get("https://data.sec.gov/submissions/CIK0000000001.json")

        self.assertEqual(caught.exception.kind, ToolErrorKind.BUDGET_EXCEEDED)

    def test_accession_key_reads_cik_and_accession(self) -> None:
        self.assertEqual(
            SecFilingDateProvider.accession_key(
                _ARCHIVE.format(cik="1577552", accession="000110465922082622")
            ),
            ("1577552", "000110465922082622"),
        )
        self.assertIsNone(SecFilingDateProvider.accession_key("https://example.test/x"))


if __name__ == "__main__":
    unittest.main()
