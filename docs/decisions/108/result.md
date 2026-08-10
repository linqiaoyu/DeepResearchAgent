# 108 result

## Why this record was written two rounds late

AGENTS.md section 9 requires every round to publish a desensitised
`docs/decisions/<round>/`. R112 audited the directory and found 092–107, 109,
110 and 111 present and 108 missing. The cause was not a lost file: R108 ran,
produced a preregistration, five counterexample logs, a paid live run and two
full gate logs, and then **never wrote a report**. The round did not close, so
nothing triggered the decision record.

This record is reconstructed by R112 from the surviving artifacts in
`_collab/108/`. It is labelled as such rather than presented as a
contemporaneous account, and it does not claim the round met a bar its own
author never asserted.

## What R108 set out to do

From `_collab/108/preregistration.md`, registered before any paid call under the
standing R107 authorisation:

> R107 delivered revenue on every run and 毛利率 on none: the topic said 毛利率,
> the planner escalated it to 主营业务毛利率, and nothing publishes that. With
> the escalation removed and 毛利率 requestable, a live run should deliver
> 毛利率 for both requested periods from AKShare's own field.

Decision rule: five conditions on the delivered `report.md`, all of which had to
hold. Circuit breakers: CNY 5 per run, CNY 20 for the round, at most 4 runs, any
run over 20 minutes killed and recorded as a failure.

## What the surviving evidence shows

| Artifact | Outcome |
|---|---|
| `evidence/live_byd.log` | Live run `57da1835`, status `done`, judge call 12,083 tokens / CNY 0.050332 / 76.1s |
| `evidence/live_byd.log` (tail) | Full package emitted; `audit_citation_closure=ok`; `exit=0` |
| `evidence/reader_contract_byd.log` | `reader_visible_contract=PASS` |
| `evidence/gate_final.log` | Full gate completed through `tracked_files_unchanged` |
| `evidence/live_source_commit.txt` | Live run made from `d833135` |

Four counterexample logs record deliberate wrong implementations failing, which
is what section 8 asks for:

- `counterexample_escalation.log` — 2 errors, 3 failures in
  `unit.test_margin_is_answered`
- `counterexample_dimension.log` — a filing's own `酒类毛利率` row must keep
  closing the strict metric
- `counterexample_percent_contract.log` —
  `reader_visible_contract=FAIL invalid_grouping_or_unit_spacing=毛利率:19.44%`
- `counterexample_rate_rendering.log` — percent spacing regression caught

The commits that carry this work are `d833135` (answer the margin the question
asked about), `58135e9` (let the reader contract read a rate) and `b6df35b`
(spend the extractor's budget on the pages that answer the question).

## Not established

- **Whether R108's own decision rule passed.** The rule required five specific
  properties of the delivered report, checked together. `reader_visible_contract`
  passing is one of them; the remaining four were never written down as met, and
  R112 will not infer a PASS from a green subset two rounds later.
- **The second registered run.** The preregistration named both 600519 and
  002594. Only the 002594 (BYD) run survives in evidence.
- **Cost for the round.** One judge call is recorded at CNY 0.050332. No
  round total was ever tallied against the CNY 20 ceiling.

## The lesson R112 took from this

A round can produce a paid live run, a passing gate and five counterexamples and
still leave no trace in the decision record, because the record is written by
the same final action that the round skipped. The rule said "末动作写 report.md"
and nothing checked that the action happened.

R112 did not add a guard for this. Publishing a decision record is a
judgement-only rule and section 11 now says so explicitly, rather than leaving
the reader to assume the directory is complete.
