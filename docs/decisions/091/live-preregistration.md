# 091 live-validation preregistration

## Authorization

The user pre-authorized paid provider calls for this and following rounds, with
an instruction to self-govern: if the same blocker consumes two or three paid
rounds without passing, stop paying and fix first before spending again.

Spend so far on this blocker: **CNY 0.000000 across 3 attempts** in R090. No
attempt reached a provider, so no paid round has been consumed yet.

## Why this run

R091 removed the two SDK imports that made R090's live validation impossible
(one per call in the worker, one in the parent). The offline guard proves the
import now happens once per worker and that startup is no longer charged to the
call timeout. It cannot prove a real provider returns a schema-valid document at
the R090 completion caps. That is what this run is for.

## Registered run

Same configuration as the R090 preregistration so the comparison isolates the
change: `--depth 1`, `--as-of 2026-07-01`, `--mode live --allow-paid-api`,
read-only `data/runtime/085-assets.db`, index
`finance_v1-43f11085-heading_page_first_1024_256`,
`DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=sec_companyfacts`.

| Run | Topic | Output |
|---|---|---|
| 1 | `蔚来 2024 年年报的营收与毛利情况` | `artifacts/091/live-nio-zh` |
| 2 (conditional) | `PDD 2024 annual report revenue and gross margin` | `artifacts/091/live-pdd-en` |

Run 2 is spent only if run 1 passes. If run 1 fails, run 2 is spent
re-validating the same topic on the fix, and PDD is reported as unvalidated.

## Breakers

Per-run CNY 0.5 (enforced by `DEEPRESEARCH_LLM_BUDGET_CNY=0.5`), round total
CNY 1.5. Stop and report on a permanent provider authorization error.

Self-governed stop rule: if two consecutive paid attempts fail for the same
cause, stop spending, fix offline, and only then spend again.

## Decision rule

Accept run 1 only if `scripts/check_llm_agent_liveness.py artifacts/091/live-nio-zh`
reports `extractor_fallback=0 reporter_fallback=0 structured_parse_errors=0
truncated_calls=0 llm_authored_claims>=3 reader_analysis_lines>=2`, and the
retained R086/R087 red lines hold: `footnote_misrefs=0`,
`magnitude_mismatches=0`, `analysis_false_positives=0`, report shape valid,
`audit_citation_closure=ok`, structured provider `SecCompanyFactsProvider`.

Any failure is recorded with its raw output and reported as INCOMPLETE.

## Expected new downstream exposure

The LLM extract and LLM report paths have not executed against a real provider
since R073/R075. Defects first surfaced by this run are in scope and must be
listed by file and line whether fixed or not. The known candidate is the
extractor's requirement that `extract_text` be a verbatim substring of the
source: the 20-F chunks contain raw HTML entities, and a model that normalizes
them would have its claims rejected (`invalid_extract_text`).
