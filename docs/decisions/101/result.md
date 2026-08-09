# 101 result

The report answers the question it was asked. For the first time in this
project's history the reader's `关键发现` states both requested periods' revenue
from a primary filing, with a citation.

```
## 关键发现
- 营业收入：NIO Inc. 2024年 年度营业收入为65,731,559,000 CNY；
  NIO Inc. 2023年 年度营业收入为55,617,933,000 CNY；
  由2024/2023两期原值机械计算同比增长18.18%。 [^3]
```

## The defect: one data source chosen before the question was known

R100's last delivery was read as a reader would read it. The question asked for
NIO's 2023 and 2024 revenue and margin; the report gave no number, its
`关键发现` said `未取得可引用的原始披露事实`, three SEC 20-F filings sat in the
reference list cited by nothing, and every cited fact came from one self-media
article. Measured:

```
evidence: 8 items, all tier=secondary, none carrying a structured record
provider_usage: {disclosure: 0, structured_data: 0, search: 4, rag_search: 1}
structured_data_stats.execution_failures = 2
  "AKShare symbol_resolve failed: timeout after 15.000s"   symbol=null
```

The cause is not a finance detail. `build_structured_data_provider` selected one
provider from the environment string `DEEPRESEARCH_STRUCTURED_DATA_PROVIDER`,
and `_configure_mode("live")` set it to `akshare`. Every live run therefore had
exactly one structured data source, fixed before the question was known. NIO is
US-listed; the request went to a China A-share source, resolution timed out
twice, and `SecCompanyFactsProvider` — which R098 verified returns
55,617,933,000 for 2023 and 65,731,559,000 for 2024 for this exact filer — was
unreachable in the same run.

Both providers already declare their surface through `supports_request`.
Nothing consulted it. **An agent that picks its data source at launch can only
ever answer about the market the operator picked**, which is the difference
between a research agent and a demo.

## Change

`CompositeStructuredDataProvider` asks each provider in turn and keeps the first
answer. A provider that misses costs a miss; a provider that raises is recorded
and skipped, which is the case that turned one timeout into an empty report.
The provider that resolved a symbol serves the follow-up request for it.

SEC is asked first because its miss is a lookup in a table it already holds,
while an AKShare miss costs the 15-second timeout. Order changes what a miss
costs, not who serves.

`auto` is the routed name and what live mode now sets. Naming a single provider
explicitly still yields exactly that provider, so the fixture path and the
reproducibility arguments built on it are unchanged.

## Live validation

`artifacts/101/live-nio-routed`, source commit `4d8122b`, CNY 0.185307.

| | R100 E3 | R101 |
|---|---:|---:|
| `provider_usage.structured_data` | 0 | **2** |
| `structured_data_stats.execution_failures` | 2 | 1 |
| `symbol_resolution_failures` | 2 | **0** |
| structured records returned | 0 | **2** |
| `grounded_key_findings` | 0 | **1** |
| `cross_source_domains` | 1 | **2** |
| `reader_analysis_lines` | 2 | 2 |
| `reporter_fallback` | 0 | 0 |

## Acceptance, including what was not met

| # | criterion | result |
|---|---|---|
| 1 | `provider_usage.structured_data >= 1` | **PASS** (2) |
| 2 | `execution_failures = 0` | **PARTIAL** (1) |
| 3 | `关键发现` states a cited revenue figure | **PASS** |
| 4 | `grounded_key_findings >= 1` | **PASS** (1) |
| 5 | offline routing guard in gate | **PASS** |
| 6 | counterexample fidelity | **PASS** (2 saved) |
| 7 | full gate does not regress | **PASS** (883 tests) |

Criterion 2 was written as zero and is one. The remaining failure is a
`StructuredDataEmptyResult` for `主营业务毛利率`: SEC Company Facts carries no
gross-margin concept, so an empty answer is the correct one and calling it an
execution failure is a mislabel. The criterion is recorded as partially met
rather than reinterpreted after the fact.

## Counterexamples

| guard | mutation | failure |
|---|---|---|
| routed selection | `auto` returns the single live provider | `FAILED (errors=1)` — `providers` attribute absent |
| provider fallthrough | a provider error aborts instead of skipping | `TimeoutError: timeout after 15.000s` propagates out of `symbol_resolve` |

## Gate

`gate_exit=0`, `Ran 883 tests ... OK (skipped=4)`, `gate created no tracked
changes`, `import_sites=0 literal_files=3 literal_hits=8` — unchanged.

## Spend

CNY 0.185307 this round, inside the per-run breaker of 0.6. Cumulative across
R099–R101: CNY 1.2275.

## Still open, by line

- **The other half of the question is unanswered.** `主营业务毛利率` reports
  `未在可用的结构化年报字段中找到该指标；可由利润表的营业收入与营业成本推算，
  本轮未作推算`. The agent names the derivation it could perform and declines to
  perform it. Whether the inputs are actually in hand is the next round's first
  measurement.
- **INCOMPLETE (medium)**: `structured_parse_errors=6`, up from 3. Six
  structured calls failed to parse and the run still completed.
- **INCOMPLETE (low)**: `orphan_footnotes=3`; one analysis line is still the
  fidelity-guard notice; citations render as `[^3] [^3]`.
