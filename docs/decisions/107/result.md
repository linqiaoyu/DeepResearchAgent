# 107 result

R105 closed with one unexplained regression and named settling it the next
round's first measurement. It is settled, and the cause was not the one R105
suspected. Fixing it made two further reader-visible defects executable for the
first time; both are fixed in the same round.

## The R105 regression — measured, not guessed

R105's A-share run delivered this to the reader:

```
关键发现: 营业收入：未取得可引用的原始披露事实
```

while the same report's coverage section quoted both years. R105 offered two
candidate causes — its own quantisation, or run-to-run plan variance — and
recorded the question rather than answering it.

The archived run survives in `artifacts/105/live-moutai-fixed`, including the
full evidence store in `runtime/research.db`. Replaying the renderer against
that exact state reproduces the defect offline and identifies it:

`_select_period_evidence` picks one evidence per period by `_evidence_rank`,
which orders `source_tier` **above** being typed. The two annual-report PDF
extracts (`source_tier="primary"`) therefore beat the two AKShare records
(`source_tier="unknown"`) — and each PDF extract was a bare digit string:

```
extract_text = '170,899,152,276.34'
```

That excerpt names no metric. `_numeric_fields_are_extract_grounded` refuses to
read a metric name into a number the source does not label, so the cited
evidence contributed **zero** values and every figure in the claim came back
unsupported. Neither quantisation nor plan variance was involved.

That refusal is correct — an unlabelled number proves nothing. What was wrong
is that it was final. One selection, no retry, so a correct guard decision cost
the reader a fact the run held in two typed records.

## Fix

Rank whole selections rather than one pick per period, and keep the first whose
rendered claim the guard accepts. A primary source that does verify still wins;
when nothing verifies, the metric still degrades to a gap.

## Downstream layers executed for the first time

`AGENTS.md` requires re-auditing downstream of a repaired layer. Once revenue
reached `关键发现` as a *cited* fact, two paths ran that never had:

**1. The citation-closure guard could not read this agent's citations.**
`check_reader_visible_contract.py` reported `footnote_misrefs=2 missing=['1',
'2']` against a report that defines both. Its definition pattern required
`http(s)://`; a structured record from an API provider cites a provider-origin
URI (`akshare://营业收入/600519/20231231/...`). The gate only ever ran this
checker's `--self-test`, whose sample sources are all SEC URLs, so the guard
passed every round while being blind to half of what this agent emits — and the
run's own `audit_citation_closure=ok` disagreed with it the whole time. The
sample now carries a provider-URI footnote.

**2. The reader was told the same thing twice.**
`_downgrade_unsupported_numeric_lines` meant to state its removal notice once.
It tested `notice in lines` while writing `"- " + notice`, so the test never
matched what it had written. R105's and R107's `详细分析` both open with the
same 47-character apology twice in a row.

## Acceptance

| # | criterion | baseline (R105) | result |
|---|---|---|---|
| 1 | `关键发现` gap lines for a cited metric | 1 | **PASS** (0) |
| 2 | requested periods delivered for 营业收入 | 0 | **PASS** (2) |
| 3 | `grounded_fact_fidelity_failure` events | 1 | **PASS** (0) |
| 4 | `check_reader_visible_contract --forbid-gap` | FAIL | **PASS** |
| 5 | placeholder bullets in `详细分析` | 2 | **PASS** (0) |
| 6 | duplicate footnote markers in a claim | 1 (`[^3] [^3]`) | **PASS** (0) |
| 7 | one figure, one rendering across sections | 2 forms | **PASS** (1) |
| 8 | offline guards in `scripts/gate.py` | none | **PASS** (10) |
| 9 | counterexample fidelity | — | **PASS** (8 saved) |
| 10 | full gate | 909 | **PASS** (919 tests) |

Criteria 1–5 are measured on the 600519 reports (runs 1–2), 6–7 on the 002594
reports (runs 3–5), each against the same-issuer baseline named in the column.

## Counterexamples

| guard | mutation | failure |
|---|---|---|
| selection retry | `for selection in selections[:0]` | `AssertionError: '未取得可引用的原始披露事实' unexpectedly found in ...` (3 tests) |
| fail-closed | delete the reporter's `is_supported` rejection | `AssertionError: '未取得可引用的原始披露事实' not found in ...` |
| tier preference | swap tier/structured in `_evidence_rank` | `AssertionError: '170,899,152,276.34' not found in ...` |
| notice repetition | restore `if notice in lines` | `AssertionError: 2 != 1` |
| footnote schemes | restore `(https?://\S+)` | `reader_visible_contract=FAIL footnote_misrefs=1 missing=['2']` |
| currency spacing | drop `_normalize_currency_spacing` | `AssertionError: '170,899,152,276.34 元' not found in ...` |
| citation dedup | rejoin markers per evidence id | `AssertionError: First list contains 1 additional elements` naming the line |

One guard was written and then removed rather than shipped: a test asserting
percentages keep their tight form could not be falsified, because the derived
comparison never passes through the normaliser. An unfalsifiable guard is worse
than none.

## Live validation

Three real layers (LLM, retrieval, disclosure) in every run. Each run on
changed code is a new experiment, so every fix below was validated after it was
written, not before.

| run | issuer | commit | cost (CNY) | result |
|---|---|---|---|---|
| 1 | 600519 | `a586a2e` | 0.1011 | R105 regression gone; exposed defects 1 and 2 |
| 2 | 600519 | `c04cbca` | 0.1077 | all criteria PASS |
| 3 | 002594 | `c04cbca` | 0.1168 | generalises; exposed defect 3 |
| 4 | 002594 | `64c2365` | 0.1107 | contract PASS; exposed defect 4 |
| 5 | 002594 | `758725a` | 0.1067 | **PASS**; defect 4 gone from 详细分析 |

Cumulative CNY 0.5429. The preregistered per-run breaker (CNY 5) and round
ceiling (CNY 20) were never approached.

Two attempts produced no result and cost nothing: run 5's first launch was
killed externally after producing only `request.json`, and its relaunch exited
1 before any paid call because the killed attempt's output directory still
existed. Both are recorded in the preregistration so the completed run is not
mistaken for a third draw.

Run 3 is where the round stopped being about one company. The BYD run selected
the *annual report* over the AKShare records — because that filing's extracts
did label their metric — which is the retry behaving as designed: it redirects
only when the best source cannot be verified, and a primary source that
verifies still wins.

## Defect 3 — one number, two renderings

`_canonical_text` quotes a verified claim verbatim, and a filing writes
`777,102,455,000元` with no space while `_format_value` writes
`602,315,354,000 元` with one. The BYD report carried both forms of the same
figure, in 关键发现 and 指标覆盖状态 respectively. The spaced form is the one
`check_reader_visible_contract.py` requires, so no `--expect` string could
satisfy both the contract and the delivered text: the report could not meet
this project's own reader-visible rendering contract. Spacing between a figure
and its currency unit is now normalised — typography only, no digit touched,
percentages untouched.

## Defect 4 — the fix that fixed one of four sites

Run 4 confirmed defect 3's fix and showed `[^3] [^3]` still live one section
down. One filing read twice resolves to one footnote, and four sites in
`reporter.py` join footnote markers per evidence id. The dedup rule already
existed, correct and commented, at exactly one of them — added in an earlier
round, never generalised. The commit that claimed defect 3 fixed the site the
failing run happened to expose and left the other two standing.

All four now share `render_citations`. A test reads the reporter's own source
and fails on any site that reintroduces per-evidence-id joining.

Repeated markers in 指标覆盖状态 are **not** this defect: that line concatenates
several distinct facts, each citing its own source, and were left alone.

## What this round does not establish

- **The notice-repetition fix was never exercised live.** It needs two
  downgraded lines in one report; runs 2 and 5 produced zero and one. It rests
  entirely on its offline guard and counterexample.
- **`actual_provider_fidelity` still records `structured_data: "unknown"`**
  though AKShare served the decisive records in all five runs. Unmeasured, so
  nothing is claimed. Next round's first measurement.
- **主营业务毛利率 was a gap in every run.** The provider returns no such field
  and the round did not attempt the derivation from revenue and cost. The
  reader is told this plainly, which is correct, but the question is only half
  answered.
- Defect 3's fix was committed as complete while covering one section of four
  citation sites. Run 4 caught it. The lesson is recorded above rather than
  smoothed over: a fix verified only where a failing run happened to look is
  not verified.
