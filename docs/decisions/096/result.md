# 096 result

## R095's reader-noise fixes, validated live

One paid run, CNY 0.134602.

| Measure | R094 | R096 |
|---|---:|---:|
| `noise_lines` | 9 | **0** |
| `duplicate_reader_lines` | 4 | **0** |
| `analysis_false_positives` | 5 | **0** |
| `orphan_footnotes` | 6 | 2 |
| `llm_authored_claims` | 0 | 3 |
| `reader_analysis_lines` | 0 | 1 |
| reporter | truncated at 8192, salvaged | `finish_reason=stop`, 7080 tokens |
| `metrics_answered` | - | 2/2 |

The reporter did not truncate. Emitting `key_findings` last -- the one field the
fidelity guard always replaces -- freed enough budget for the rest of the draft
to complete, which is what R095 predicted and what R094's cut had destroyed.

The delivered risk section is now five model-authored research limitations with
no duplicates and no filing-age false positives, including one the reader could
act on: that the 9.9% margin is derived rather than disclosed, and that a VIE's
RMB 31.3m of revenue must not be read together with RMB 126.3m of intra-group
services.

## What this run exposed

Web-source period governance fired on real web results for the first time:

```
web_source_governance rejected nio-20231231x20f.htm      (off_target_reporting_period)
web_source_governance rejected carnewschina.com/2026/03/11/...  (off_target_reporting_period)
```

It correctly refused NIO's 2023 20-F and a 2026 news article for a 2024
question. R086 built that rule; until R094 restored web search it had never had
a real web result to govern. `refused_by` is null on both, correctly
distinguishing a governance rejection from a self-refusal.

The consequence is that no web evidence survived, so this run's evidence was
again RAG plus structured. Web search working and web evidence surviving
governance are two different things.

## Not met

`reader_analysis_lines=1`, one short of the threshold, and `truncated_calls=2`
-- two of eight extractor batches. Those batches failed independently and cost
one source each rather than the extraction, which is the R093 design working,
but the extractor still overruns its cap on some sources.

## The concurrency flake: hardened, not fixed

`test_independent_request_engines_share_wal_checkpoint_safely` fails
intermittently with `database is locked`. Measured, not assumed:

| | failures |
|---|---|
| before | 1 / 12 |
| store connection `IMMEDIATE` | 1 / 12 |
| both connections `IMMEDIATE` | 1 / 36 |

Both connections now take the write lock when the transaction opens and set
`busy_timeout` before `journal_mode=WAL`, which removes a real class of
lock-upgrade failure that `timeout` cannot cover. **It does not close the
flake**, and 1/36 against 1/12 is not a sample that supports claiming a
reduction. Recorded as hardening; the flake remains open.

## Still open, by line

- **INCOMPLETE (high)**: `reader_analysis_lines=1`, threshold 2. The renderer
  keeps at most three analysis claims per sub-question and drops those not
  related to a key finding; with one sub-question and mechanical key findings
  the ceiling is thin.
- **INCOMPLETE (medium)**: two of eight extractor batches still truncate.
- **INCOMPLETE (medium)**: the concurrency flake above.
- **INCOMPLETE (medium)**: R094's observation stands -- for an A-share topic the
  RAG corpus (60 SEC 20-F documents) and SEC Company Facts are both empty and
  only CNINFO plus web remain. That configuration has never been run live.
