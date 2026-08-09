# 103 result

The report no longer contradicts itself. The metric that is not directly
disclosed now points at the value that fills it:

```
## 关键发现
- 主营业务毛利率：结构化年报字段未直接披露该指标；已由营业收入与毛利逐期推导，
  推导值见「派生指标」（2023-12-31、2024-12-31），其分子分母与出处一并列出。

## 派生指标
- 2023-12-31 毛利率（推导值）：3,051,796,000 / 55,617,933,000 = 5.49% [^2]
- 2024-12-31 毛利率（推导值）：6,492,762,000 / 65,731,559,000 = 9.88% [^2]
```

## The defect, which R102 created

R102 delivered the derivation and left the notice above it reading
`可由利润表的营业收入与营业成本推算，本轮未作推算` — two lines above the section
performing exactly that derivation. Fixing half a problem produced a report that
states a gap in the same breath as the value filling it.

The metric is genuinely not disclosed directly, so it stays a gap. What changed
is that the notice is written from what actually happened.

## Changes

- `reader_metric_gap_explanation` takes the periods that were derived and says
  so; with none, the plain gap wording is unchanged.
- Both sections carrying that wording — `关键发现` and `指标覆盖状态` — read the
  same source, so they cannot drift apart again.
- Which metrics were derived is a domain judgement (the derivation labels its
  result `毛利率`, the question asks for `主营业务毛利率`), so `derived_metric_periods`
  is a pack method and the reporter learns no metric name.

## Live validation

`artifacts/103/live-nio-consistent`, source commit `a3e5c6c`, CNY 0.172029.

| | R102 | R103 |
|---|---:|---:|
| occurrences of `本轮未作推算` alongside a derivation | 1 | **0** |
| derived margin periods delivered | 2 | 2 |
| `grounded_key_findings` | 2 | 2 |
| `reader_analysis_lines` | 1 | 1 |
| `downgraded_numeric_lines` | 4 | 4 |

## Acceptance

| # | criterion | result |
|---|---|---|
| 1 | no `本轮未作推算` where a derivation exists | **PASS** (0) |
| 2 | the notice names the derived periods | **PASS** |
| 3 | a metric with no derivation still reports the gap plainly | **PASS** (guarded) |
| 4 | offline guard in gate | **PASS** |
| 5 | counterexample fidelity | **PASS** |
| 6 | full gate does not regress | **PASS** (892 tests) |

## Counterexample

| guard | mutation | failure |
|---|---|---|
| gap notice knows the derivation | ignore `derived_periods` | `AssertionError: '本轮未作推算' unexpectedly found ... the report states a gap in the same breath as the value that fills it` |

## Gate

`gate_exit=0`, `Ran 892 tests ... OK (skipped=4)`, `import_sites=0
literal_files=3 literal_hits=8` — unchanged.

## Spend

CNY 0.172029 this round. Cumulative R099–R103: CNY 1.5887.

## Still open

- **The analysis section is mostly boilerplate.** `downgraded_numeric_lines=4`
  and `reader_analysis_lines=1`: four of the five rendered analysis lines are
  the same fidelity-guard notice, printed once per line. Unchanged by this
  round and the next entry point.
