# 090 live-validation preregistration

## Why a paid run is required

The offline guard added this round proves that the extractor and reporter
completion caps can carry their own schemas under a provider stub that
truncates at `max_tokens`. It cannot prove that the real provider returns a
schema-valid document at the new cap. Only a live run distinguishes
"configuration no longer forces truncation" from "the LLM agents actually ran".

## Authorization

The user authorized, in this round, two live runs with a CNY 1.5 round breaker
and a CNY 0.5 per-run breaker. Providers: DeepSeek (planner, extractor,
reporter, capability_selector), DashScope (judge, citation_support, embedding,
rerank), Tavily (web search), SEC EDGAR Company Facts (structured data). No
further paid calls are authorized in this round, including retries for a better
result.

## Hypothesis

Raising `extractor` and `reporter` `max_completion_tokens` from 1024 to 4096,
with their role timeout raised to 180s, removes the truncation that forced both
agents into their deterministic fallbacks in all 28 packages of rounds 086-087.

## Registered runs

Both runs use the same source commit, `--depth 1`, `--as-of 2026-07-01`,
`--mode live --allow-paid-api`, the read-only `data/runtime/085-assets.db`
corpus, index `finance_v1-43f11085-heading_page_first_1024_256`, and
`DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=sec_companyfacts` — identical to the
R087 configuration so the comparison isolates this round's change.

| Run | Topic | Output |
|---|---|---|
| 1 | `蔚来 2024 年年报的营收与毛利情况` | `artifacts/090/live-nio-zh` |
| 2 | `PDD 2024 annual report revenue and gross margin` | `artifacts/090/live-pdd-en` |

## Measurement

For each package, `scripts/check_llm_agent_liveness.py <package>` reports:

```
extractor_fallback= reporter_fallback= structured_parse_errors= truncated_calls=
llm_authored_claims= reader_analysis_lines= orphan_footnotes=
```

The R086/R087 baseline for every one of the 28 stored packages is
`1 / 1 / 4 / 4 / 0`, recorded in `_collab/090/evidence/baseline_087_086.log`.

`reader_analysis_lines` counts cited bullets that survive into `## 详细分析` in
the delivered `report.md`. It exists because `llm_authored_claims` is a pipeline
property: two separate downstream steps could record authored claims and still
show the reader nothing (see "downstream defects" below). `orphan_footnotes` is
reported, not enforced, this round.

## Decision rule

Accept only if both packages report `extractor_fallback=0`,
`reporter_fallback=0`, `structured_parse_errors=0`, `truncated_calls=0`,
`llm_authored_claims >= 3` and `reader_analysis_lines >= 2`, **and** the
retained R086/R087 red lines hold:
`footnote_misrefs=0`, `magnitude_mismatches=0`, `analysis_false_positives=0`,
report shape valid, `audit_citation_closure=ok`, structured provider identity
`SecCompanyFactsProvider`.

A run that fails any of these is recorded as a failure with its raw output and
reported as INCOMPLETE.

Run allocation is sequential: run 1 is NIO, run 2 is PDD. If run 1 exposes a
downstream defect first reached by the now-live LLM path, run 2 may be spent
re-validating NIO on the fix instead of running PDD; PDD is then reported as
unvalidated and INCOMPLETE. This is the only permitted reallocation, and it is
not authorization to repeat a completed run for a better number.

## Circuit breakers and rollback

Stop immediately and report if a single run exceeds CNY 0.5, if the round total
reaches CNY 1.5, or if a provider returns a permanent authorization error.
Rollback is a revert of the two `max_completion_tokens` values; the observability
and guard changes stand independently of the live outcome.

## Downstream defects found before spending

Per AGENTS.md §7, the LLM extract and LLM report paths have not executed since
R073/R075, so their downstream code has never run in a live package. Two
defects were found by reading that code before the paid runs, and both are
fixed in this round's source; without them the acceptance above is unreachable
no matter how good the model output is.

1. `src/deepresearch_agent/agents/reporter.py` `_compact_reader_report` deleted
   `## 详细分析` from every finance report unconditionally. Correct while the
   section held deterministic filing boilerplate; it now discards the only
   prose that answers the question. The section is carried through exactly when
   the reporter did not fall back.
2. `src/deepresearch_agent/agents/reporter.py` `_render_llm_report` dropped any
   analysis claim whose cited evidence had already been cited by a key finding.
   The reporter contract deduplicates *numeric facts*, but the rule was keyed on
   evidence identity, so for a single-metric question every analysis claim was
   deleted before rendering. The rule now applies only to claims that restate a
   number.

Defects first surfaced by the live runs themselves remain in scope and must be
listed by file and line whether fixed or not.
