# 097 result

## The finding: the machinery for multi-period research existed and was never asked to run

`metric_coverage` has supported multiple requested periods since R087. It
renders `请求报告期：2024, 2025` and reports each period's status separately;
`tests/unit/test_reporter_finance_template.py` has exercised the two-period path
since then.

The planner never used it. `prompts/planner.md` offered exactly one example,
`optional periods like 20241231`, and said nothing about comparison questions,
so every plan requested a single period.

Measured across every stored delivery:

| package | periods_compared | cross_source_domains |
|---|---:|---:|
| R087 | 1 | 1 |
| R093 | 1 | 1 |
| R094 | 1 | 2 |
| R096 | 1 | 1 |

**No report this project has ever produced answers more than one reporting
period.** Not because the model could not, but because nothing ever asked for
the second one. This is the quantified form of the reason the harness's
capability stayed invisible: a question answerable by one lookup in one
document does not need an agent, and every acceptance criterion up to R096
measured whether the machinery ran rather than whether research happened.

## Changes

- `prompts/planner.md`: a question about a change, trend or year-on-year move
  must request every period the comparison needs; a multi-part question is
  decomposed rather than collapsed into one sub-question. Prompt drift
  registered, golden snapshots updated for the hash alone.
- `scripts/check_llm_agent_liveness.py`: two measures of research behaviour
  rather than pipeline health.
  - `periods_compared` — reporting periods the reader's coverage section
    answers for, read from the rendered `请求报告期` lists.
  - `cross_source_domains` — distinct hosts actually cited in the body.
  Both are reported for every package and enforced only via
  `--min-periods-compared` / `--min-source-domains`, because a single-period
  question honestly answers one period.

The period measure was built twice. The first version counted four-digit years
in cited prose lines and scored R093 at 2 — it was reading `2025-04-08`, a
document's publication date, as a reporting period. Counting the rendered
coverage list instead cannot make that mistake, and a guard pins it.

## Live validation: not completed in this round

The multi-period run was launched against commit `74f9153`
(`蔚来 2023 与 2024 年营收和毛利率的变化及其驱动因素`, depth 2) and the round was
closed before its result could be folded in. The A-share run was not launched.
Both are the next round's entry point, with the acceptance below.

## Next round's acceptance

```
scripts/check_llm_agent_liveness.py artifacts/098/live-nio-multiperiod \
    --min-periods-compared 2 --min-source-domains 2
extractor_fallback=0 reporter_fallback=0 truncated_calls=0
periods_compared>=2 cross_source_domains>=2 reader_analysis_lines>=2
```

Baseline for every one of those: `periods_compared=1`, and
`cross_source_domains=1` in three of the four stored packages.

## Still open, by line

- **INCOMPLETE (high)**: multi-period live validation, above.
- **INCOMPLETE (high)**: the A-share path has never run live. For a 600519 or
  300750 topic the frozen RAG corpus (60 SEC 20-F documents) and SEC Company
  Facts are both empty, leaving CNINFO plus web. `researcher.py:160` requires an
  unambiguous six-digit code, correctly refusing to invent one, so the path is
  reachable only from an A-share topic — and no such topic has ever been run.
- **INCOMPLETE (high)**: `reader_analysis_lines=1` against a threshold of 2 in
  R096.
- **INCOMPLETE (medium)**: two of eight extractor batches still truncate.
- **INCOMPLETE (medium)**: `test_independent_request_engines_share_wal_checkpoint_safely`
  fails intermittently with `database is locked` (1/36 after R096's hardening,
  1/12 before).
