# Evaluation Harness

The harness treats evaluation as a first-class subsystem, not a screenshot.

## Metrics

- `task_success_rate`: report generated with at least one evidence record
- `citation_accuracy`: in deterministic mode, citation markers in bullet claims map to Evidence rows and the cited claim has deterministic text overlap with `Evidence.claim` or `Evidence.extract_text`; in LLM mode this is `null` with a reason because paraphrase-aware judging is not implemented yet
- `citation_resolution_rate`: citation markers that resolve to real Evidence rows, computed in both deterministic and LLM modes
- `critic_catch_rate`: MVP heuristic/proxy for whether the Critic exposed quality issues. Current deterministic logic scores visible issue coverage, using `min(1.0, len(issues) / 3)` when issues are present and `1.0` when no issues are found. It is not true seeded issue recall or human-labeled Critic recall.
- `answer_relevance`: topic terms appear in the final report
- `faithfulness`: bullet claims in the report carry citations
- `cost_usd`, `cost_cny`, `latency_seconds`, `token_used`, `price_source`: operational metrics for Pareto analysis. LLM mode accounts natively in CNY from the LiteLLM ledger.

Unsupported or invalid bullet citations are counted as `citation_error` bad cases in deterministic scoring. In LLM mode, unresolved citation markers are counted mechanically; semantic citation support waits for the judge task.

Production version: compute true critic recall from seeded issues or manually labeled bad cases.

## Golden Recording Controls

Golden Set live recording uses the search recording layer in `record` mode and
requires an explicit `DEEPRESEARCH_AS_OF`; the recording metadata uses that
runtime value as the single as-of source. Tavily read timeout defaults to 60
seconds, failed individual queries are recorded as partial instead of aborting
the run, and existing recording keys are replayed idempotently on rerun. Each
run stops issuing additional searches after `DEEPRESEARCH_MAX_SEARCHES_PER_RUN`
(default `20`). Tavily `raw_content` is capped per source by
`DEEPRESEARCH_TAVILY_RAW_CONTENT_CHAR_LIMIT` (default `40000` characters) before
extraction.

## Frozen Corpus Replay

Exact-key replay was retired for Golden Set evaluation. The prior design keyed
recordings by the literal LLM-generated query, `top_k`, and `source_type`, but
temperature-zero LLM planning still produced byte-level query drift across runs.
That made otherwise valid recorded corpora fail replay with exact-key misses.

Replay mode now treats `data/recordings/golden_v1/` as a frozen corpus. It loads
all recorded sources with non-empty content, excludes zero-source recordings,
and ranks sources for any incoming query with deterministic lexical overlap over
title and body. `source_type` is respected first; if the filtered set has no
candidate, replay falls back to all source types. Replay mode does not call
external search services and does not write the recording directory.

This is a deterministic evaluation mechanism, not a claim that Tavily would
return the same ordering live. Frozen-corpus results are bounded by corpus
coverage and lexical ranking quality. Each freeze records the runtime `as_of`
date and a directory content hash so score changes can be tied to a specific
corpus snapshot.

## Golden Questions

`data/eval_set_deterministic.jsonl` contains 50 deterministic CI regression cases covering financial AI, wealth management, citation verification, Evidence Store design, Critic loops, checkpointing, Docker deployment, and interview packaging.

Run:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5
```

The command writes `artifacts/evaluation/latest_metrics.json`.

## Metric Diff

`data/eval_baseline.json` stores the deterministic MVP baseline for a 5-case
local sweep. Compare a new run against it with:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline
```

Use a custom baseline path when validating an experiment:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline --baseline-path artifacts/evaluation/latest_metrics.json
```

The comparison gates quality regressions for `avg_citation_accuracy`,
`avg_citation_resolution_rate`, `avg_faithfulness`, `avg_critic_catch_rate`, and total bad-case count.
`avg_cost_usd`, `avg_latency_seconds`, and `avg_token_used` are reported as
operational diffs; latency changes are informational so local machine variance
does not fail the smoke check.

## Current Deterministic Baseline

Task 8 packaging validation uses the repo-local Python 3.12 environment and the
deterministic fixture path. It does not require external LLM/search keys.

- Tests: full `unittest` suite passes
- Demo: `phase=done status=done`
- Demo artifact: `artifacts/demo_report.md`
- Checkpoint demo: `paused_phase=critiquing paused_status=paused`, then `resumed_phase=done resumed_status=done`

Deterministic evaluation sweep: `PYTHONPATH=src .venv/bin/python scripts/run_eval.py --limit 5 --compare-baseline`

| Metric | Value |
| --- | ---: |
| `cases` | `5` |
| `avg_task_success_rate` | `1.0` |
| `avg_citation_accuracy` | `1.0` |
| `avg_citation_resolution_rate` | `1.0` |
| `avg_critic_catch_rate` | `0.8` |
| `avg_answer_relevance` | `1.0` |
| `avg_faithfulness` | `0.923` |
| `avg_cost_usd` | `0.023` |
| `avg_token_used` | `9644.8` |
| `bad_case_categories.numeric_conflict` | `6` |

The baseline comparison status is `pass`. Latency is reported as an
informational operational diff because it varies by local machine.

This is a deterministic local fixture run for Gate 4 review, not a production LLM/search benchmark. It does not imply Tavily, LiteLLM, Postgres, or LangGraph production integrations are complete.

## Bad Case Categories

The default Critic and seed data support these categories:

- retrieval miss
- citation error
- numeric conflict
- temporal conflict
- outdated source
- missing counterargument
- unverified projection

## Acceptance Criteria

- Evaluation can be run repeatedly from the command line.
- The output includes quality, citation, cost, latency, token, Critic catch rate, and aggregated bad-case fields.
- Critic issues are visible in the Streamlit dashboard and final report.
