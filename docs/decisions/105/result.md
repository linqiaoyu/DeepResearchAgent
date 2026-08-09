# 105 result

The first live validation against a second issuer. Every run from R099 to R104
used one topic and one filer, which `AGENTS.md` names as the project's first
risk — degenerating into a single-company report reader. Two reader-visible
defects appeared immediately, both invisible on the original topic. Both are
fixed and confirmed. A third finding is an unexplained regression and is
recorded as such.

## What generalised

Routing (R101) resolved the A-share issuer with zero resolution failures and
served it from the A-share provider. Component expansion (R102), the
no-contradiction rule (R103) and the English-filing parser (R104) all behaved.
`periods_compared=2`, `reporter_fallback=0`, `cross_source_domains=2–3`.

## Defect 1 — four wrong decimals of a yuan

```
营业收入：600519 2024年 累计营业收入为174,144,069,958.24997 元
```

Two faults. The provider converted every reported amount to a binary float
while the record field is a `Decimal`, so the float's binary expansion became
the value. And nothing bounded the precision afterwards.

Money no longer passes through a binary float, and an amount in a currency is
quantised to that currency's smallest unit — no filing reports a fraction of a
fen, and carrying one forward only launders the provider's arithmetic residue
into a figure that looks precise. Quantisation is by unit, so a rate or a count
keeps its precision.

Invisible on the original topic because the SEC provider returns integer XBRL
facts.

Confirmed live: the record now reads `174144069958.25`, the filed figure, and
the string `24997` appears nowhere in the delivered report.

## Defect 2 — a computation's input reported as a missing answer

```
毛利：未取得可引用的原始披露事实；可查阅对应年度报告或原始披露补充核验。
```

Nobody asked about it. R102 began appending that input so the requested ratio
could be derived, and every appended input became a reader-facing required
metric — invisible while it resolved, and on the first issuer where it did not,
presented as a metric the research failed to find.

A request now records why it exists, and coverage reports only what the question
asked for. The input is still fetched and still feeds the derivation. A metric
the question does name stays reader-facing even when it is also an input.

Confirmed live: no such line in the delivered report.

## Acceptance

| # | criterion | baseline | result |
|---|---|---|---|
| 1 | no sub-fen precision in a delivered amount | `.24997` | **PASS** (0 occurrences) |
| 2 | the record carries the filed figure | `174144069958.24997` | **PASS** (`174144069958.25`) |
| 3 | no component reported as a reader-facing metric | 1 line | **PASS** (0) |
| 4 | a named metric stays reader-facing | — | **PASS** (guarded) |
| 5 | offline guards in gate | none | **PASS** |
| 6 | counterexample fidelity | — | **PASS** (2 saved) |
| 7 | full gate | 900 | **PASS** (909 tests) |

The first gate attempt failed `check_domain_boundary.py`: a schema comment in a
core file named two finance metrics, raising `literal_hits` from 8 to 9.
Reworded; the ratchet is unchanged.

## Counterexamples

| guard | mutation | failure |
|---|---|---|
| currency quantisation | carry the provider's residue | `AssertionError: 5 not less than or equal to 2 : '174144069958.24997' kept sub-fen precision` |
| component is not an answer | report components as metrics | `AssertionError: '毛利' unexpectedly found in {'毛利', '营业收入', '主营业务毛利率'}` |

## Spend

CNY 0.177223 + 0.112328 this round. Cumulative R099–R105: CNY 2.2284.

## INCOMPLETE — an unexplained regression in the same run

The pre-fix A-share run put both years' revenue in `关键发现`. The post-fix run,
same topic, did not:

```
关键发现: 营业收入：未取得可引用的原始披露事实
```

The records are present and correct in both runs — two structured records,
identical source URLs and tiers, differing only in the precision this round
fixed. Both runs report `grounded_key_findings=1`, but in the second the
revenue claim moved into `grounded_gaps`, meaning it was built and then rejected
by the fidelity check.

**Cause not established.** It may be this round's quantisation changing a value
the fidelity comparison depends on, or it may be run-to-run variance in the
plan (the two runs produced different sub-question ids and different period
handling). Naming one without measuring it is what this project's method
forbids, so it is recorded unexplained and is the next round's first
measurement. Until it is settled, this round's two fixes are confirmed and the
A-share revenue path is not.
