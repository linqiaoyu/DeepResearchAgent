# 104 result

The numeric fidelity guard can read the filings this agent retrieves. Boilerplate
in the analysis section fell from four lines to one, and the reader gets two
cited analysis lines again.

## The defect: the better the source, the more analysis was deleted

R103's live run rendered five analysis lines and the reader received one. Four
were replaced by `该数值表述未通过 Evidence 保真守卫`, printed once per line.
Every one of them cited a primary English 20-F, and every one stated its
source's own numbers:

```
CLAIM  2023年毛利率5.5%，低于2022年的10.4%
EVID   Gross margin in 2023 was 5.5%, compared with 10.4% in 2022.   -> rejected

CLAIM  2024年第一季度总营收99.09亿元
EVID   Total revenues were RMB9,908.6 million (US$1,372.3 million)   -> rejected
```

Measured cause: `_extract_text_values` returned `[]` for every English evidence
text. Its metric patterns and unit table were Chinese-only, so a claim citing an
English filing had no support by construction. For a US-listed issuer the 20-F
is the best source this agent has — so the guard was strictest exactly where the
grounding was strongest.

## Changes, none of which relax the guard

- English metric names, so `Gross margin` binds like `毛利率`.
- The scales an English filing prints, so `RMB9,908.6 million` reads as 99.09亿元.
- The year, which English puts *after* the figure. Reading backwards gave
  `was 4.9% in ... 2024, compared with 1.5% in ... 2023` no year for the first
  figure and the wrong year for the second. The forward search stops at the next
  *measured* figure rather than the next digits, because the year being searched
  for is itself four digits.

An English scale counts as CNY only where the filing says RMB, so the
`US$1,372.3 million` a 20-F prints beside it can never support a yuan claim, and
an unqualified scale supports nothing. Fabricated figures, wrong-year
attributions and dollar-for-yuan reads are each still rejected, each with a test
that fails if that stops being true.

## Live validation

`artifacts/104/live-nio-english`, source commit `04295ef`, CNY 0.150132.

| | R103 | R104 |
|---|---:|---:|
| `downgraded_numeric_lines` | 4 | **1** |
| boilerplate lines in `## 详细分析` | 4 | **1** |
| `reader_analysis_lines` | 1 | **2** |
| `reporter_fallback` | 0 | 0 |
| `grounded_key_findings` | 2 | 2 |

## Acceptance

| # | criterion | baseline | result |
|---|---|---:|---|
| 1 | `downgraded_numeric_lines <= 1` | 4 | **PASS** (1) |
| 2 | `reader_analysis_lines >= 2` | 1 | **PASS** (2) |
| 3 | boilerplate lines `<= 1` | 4 | **PASS** (1) |
| 4 | fabrication still rejected | — | **PASS** (4 controls) |
| 5 | offline guard in gate | none | **PASS** (8 tests) |
| 6 | counterexample fidelity | — | **PASS** (3 saved) |
| 7 | full gate | 892 | **PASS** (900 tests) |

## Counterexamples

| guard | mutation | failure |
|---|---|---|
| English metric names | remove the English patterns | 3 x `AssertionError: True is not false` |
| currency discipline | accept any scale as CNY | `AssertionError: False is not true` — a dollar figure supports a yuan claim |
| English word order | read the year backwards only | 2 x `AssertionError: True is not false` |

## Spend

CNY 0.150132 this round. Cumulative R099–R104: CNY 1.7388.

## A note on this run's remaining hedging

Two of the three analysis lines read `证据未提供具体驱动因素细节`. That is
honest: this run's evidence store held four structured records and no filing
prose at all, so there were no drivers to cite. Retrieval returned English 20-F
prose in R103 and none in R104 on the same topic and prompt — the variance is
real and is not addressed here.

## Still open

- **Every live validation in R099–R104 used one topic and one issuer.** A
  harness that only works for this filer is still a single-company report
  reader, which is the risk `AGENTS.md` names first. Generalisation has not been
  measured and is the next entry point.
- `structured_parse_errors` 3–6 per run, undiagnosed.
- `orphan_footnotes` 3–4: references listed and cited by nothing.
