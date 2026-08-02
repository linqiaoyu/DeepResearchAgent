# 064 — SEC Company Facts for 20-F structured facts

## Decision

Use the SEC EDGAR Company Facts REST API as the real structured-data provider
for US-listed 20-F issuers.  The adapter is selected explicitly with
`DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=sec_companyfacts`; the live package
preserves an explicit provider choice and otherwise retains its AKShare default
for the existing mainland-equity path.

## Evidence and boundary

The SEC documents that `data.sec.gov` requires no API key and that Company
Facts aggregates XBRL data from 20-F filings.  The adapter uses only the public
`company_tickers.json` and `companyfacts/CIK##########.json` endpoints, with a
per-attempt transport timeout, at most three attempts, and workflow-scoped
external-fetch budget consumption before every egress.  It accepts an exact
ticker/CIK/registrant identity, or a domain-owned issuer alias; it does not
guess a similar issuer.  Each normalized fact retains its SEC archive URL.

`price_history` is explicitly inapplicable to this filing-facts provider:
Company Facts has no exchange-price observations.  The researcher records such
a planned request as `inapplicable_requests` without calling an unrelated
provider or manufacturing a value.  Financial facts remain real provider use.

## Verification

The offline MockTransport guard resolves the Chinese Alibaba alias, rejects a
6-K comparative fact, preserves the 20-F archive URL, and exercises one bounded
HTTP retry.  The zero-cost live SEC probe returned Alibaba FY2024 revenue
`941168000000 CNY` and attributable net income `80009000000 CNY`, both dated
2024-03-31 and linked to the 2024 20-F archive.  Mutation evidence demonstrates
that deleting the 20-F filter and deleting the provider-applicability guard each
make their respective tests fail.

No external code was copied.  The SEC API is a public data service; its data
source is recorded in delivered evidence rather than treated as a dependency
license.
