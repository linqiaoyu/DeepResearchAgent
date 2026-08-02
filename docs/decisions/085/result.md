# 085 result

## Measured result

The new corpus copy contains `60/60` verified SEC filing dates; `0` are
fabricated and all 60 are later than their reporting-period ends.  The
immutable 047 database SHA-256 was `ddd32915f457092bc3aafc2ded9e18d8c313e4efa6d1a33ae47fb5fc6b6911a3`
both before and after.  The 085 copy was idempotent at
`31f82467ab3a24cfd7beb519386a3fd15e9ef49f58c76dd8263308e57b8ee4a0`.

The offline period probe produced `period_labels=2023,2024`, 100 lexical
candidates and zero off-scope candidates.  The source-quality probe rejected
3/3 observed semantic error-page forms, removed 3 boilerplate markers, and
retained the numeric financial sentence.  The 084 NIO baseline had 55
footnotes over 19 source URLs (36 duplicates); the new NIO/PDD packages had
`17/17/0`, `13/13/0`, and `17/17/0` respectively.

## Live outcome: INCOMPLETE

Three authorized executions cost CNY `0.025592 + 0.024196 + 0.02534984 =
0.07513784`, below CNY 20.  NIO and its one allowed retry each yielded
`sampled_numbers=1` (required >=2) and `off_year_ratio=0.38` (required <=0.20).
PDD yielded `sampled_numbers=1`; its `off_year_ratio=0.00` passed.  All three
had `verdict=PASS`, zero duplicate footnotes, and SEC Company Facts as the
structured provider.  No further retries are authorized.

## 086 decision

Do not pay CNY 11.74 for re-embedding before resolving the measured retrieval
failure: NIO off-year ratio is 0.38, 0.18 above the 0.20 threshold, and both
topics sampled only 1 required numeric datum.  HTML entity pollution remains
21839/22953 chunks (95%).  Excluding 665 XBRL-context chunks (3%) would save
only about CNY 0.34.  If 086 proceeds, require both topics to reach
`off_year_ratio <= 0.20`, `sampled_numbers >= 2`, zero error-page citations,
and source-URL footnote deduplication before comparing re-embedding quality.

## Authorized retry result

The retry at commit `7372acf50575191d671d08a1b1224faa678d8428` cost CNY
`0.02543256`.  It produced NIO `sampled_numbers=2`, `off_year_ratio=0.00`,
`footnote_count=13`, `distinct_source_urls=13`, `duplicate_footnotes=0`, and
`verdict=PASS`; both `65,731,559,000 CNY` revenue and `6,492,762,000 CNY`
gross profit remain in the report.  The structured provider was
`SecCompanyFactsProvider`.
