# 102 result

The other half of the question is answered. The reader gets gross margin for
both requested years, with the arithmetic and the source:

```
## 派生指标
- 2023-12-31 毛利率（推导值）：3,051,796,000 / 55,617,933,000 = 5.49% [^1]
- 2024-12-31 毛利率（推导值）：6,492,762,000 / 65,731,559,000 = 9.88% [^1]
```

Revenue +18.18%, gross margin 5.49% to 9.88%. The question — how did revenue
and margin change, and why — now has both of its numbers.

## The defect: naming a derivation instead of performing it

R101's report said, of the metric it could not find:

> 可由利润表的营业收入与营业成本推算，**本轮未作推算**

Every ingredient was already in the repository. One free request to the filer's
Company Facts settled it:

```
GrossProfit                        2023: 3,051,796,000   2024: 6,492,762,000
RevenueFromContractWithCustomer... 2023: 55,617,933,000  2024: 65,731,559,000
```

`SEC_COMPANYFACTS_CONCEPTS` already mapped `毛利` to `GrossProfit`.
`reader_derived_metrics` already divided one by the other. The reporter already
had a `## 派生指标` slot. The single missing link was that structured requests
were built from the words in the question, and `主营业务毛利率` is listed as
unsupported by that provider — so nothing ever asked for `毛利`, and the
derivation never had an input.

A research agent that cannot fetch the numerator and denominator of a ratio it
already knows how to compute is not doing research.

## Changes

- `METRIC_COMPONENTS` records what a metric can be computed from. Only exact
  identities; a ratio whose inputs need an estimate is not a derivation.
- The planner appends those components to the request set — appended, not
  substituted, so a source that publishes the metric directly still answers it.
- `reader_derived_metrics` derives per period. It previously kept whichever
  revenue and whichever gross profit came last and ignored the period, which
  can divide one year's profit by another year's revenue without saying so.
- The reporter renders one line per period, and deduplicates citations by
  footnote rather than by evidence id, so two facts from one filing no longer
  print `[^1] [^1]`.

## Live validation

`artifacts/102/live-nio-derived`, source commit `421ed3e`, CNY 0.189238.

| | R101 | R102 |
|---|---:|---:|
| derived margin periods delivered | 0 | **2** |
| `provider_usage.structured_data` | 2 | **4** |
| structured records | 2 | **4** |
| `grounded_key_findings` | 1 | **2** |
| `reader_analysis_lines` | 2 | **1** |
| `downgraded_numeric_lines` | 1 | **4** |

## Acceptance

| # | criterion | result |
|---|---|---|
| 1 | both periods' margin reach the reader | **PASS** (2) |
| 2 | each shows numerator, denominator and a footnote | **PASS** |
| 3 | rendered in a reader-visible section, marked derived | **PASS** (`## 派生指标`, `推导值`) |
| 4 | structured records >= 4 | **PASS** (4) |
| 5 | offline guard in gate | **PASS** |
| 6 | counterexample fidelity | **PASS** (3 saved) |
| 7 | full gate does not regress | **PASS** (887 tests) |

## Counterexamples

| guard | mutation | failure |
|---|---|---|
| component request | request only the literal metrics | `AssertionError: '毛利' not found in {'营业收入', '主营业务毛利率'}` |
| per-period rendering | render only `metrics[0]` | `AssertionError: 1 != 2 : one line per period` |
| period pairing | ignore the period when pairing | `AssertionError: Lists differ: ['ANY'] != ['20241231']` |

## Gate

`gate_exit=0`, `Ran 887 tests ... OK (skipped=4)`, `import_sites=0
literal_files=3 literal_hits=8` — unchanged.

Four planner tests asserted the exact request list and gained an entry each.
Each was updated to name the appended component explicitly rather than relaxed:
the ordered-list comparisons still fail if any request is dropped.

## Spend

CNY 0.189238 this round. Cumulative R099–R102: CNY 1.4167.

## What this round's own delivery exposes

Two problems, both visible in the report above, both created or worsened here:

- **The report contradicts itself.** `关键发现` still carries
  `主营业务毛利率：未在可用的结构化年报字段中找到该指标；可由利润表的营业收入与
  营业成本推算，本轮未作推算` — two lines above the section that performs
  exactly that derivation. The gap notice is written by the coverage policy,
  which does not know the derivation happened.
- **The analysis section is mostly boilerplate.** `reader_analysis_lines` fell
  from 2 to 1, and 4 of the 5 rendered analysis lines are the fidelity-guard
  notice, repeated verbatim. `downgraded_numeric_lines` rose from 1 to 4.

Neither is cosmetic: a report that states a gap it has just filled, and whose
analysis section is four copies of an apology, is not usable output. They are
the next round's entry point.
