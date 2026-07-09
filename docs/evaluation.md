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

Unsupported or invalid bullet citations are counted as `citation_error` bad cases in deterministic scoring. Golden Set LLM rounds additionally run a judge-backed `citation_support_rate` over extracted report claims and evidence.

Production version: compute true critic recall from seeded issues or manually labeled bad cases.

## Golden Set v1

Golden Set v1 is frozen under `data/golden_set/v1/` with version `v1.0`.
It contains 30 finance-oriented cases across 财报解读, 对比研究, 行业研究,
and 事件时间线. The frozen set records gold facts, source references, the
quarantine list, freeze-time adjustments, the evaluation `as_of`, recording
`as_of` distribution, and the frozen corpus fingerprint.

Frozen assets:

- `data/golden_set/v1/questions.json`: 30 cases with source-backed gold fields.
- `data/golden_set/v1/freeze.md`: freeze note, corpus stats, quarantine list, and adjustments.
- `data/golden_set/v1/results/round1.json`: first full judge round.
- `data/golden_set/v1/results/round2.json`: second full judge round.
- `data/golden_set/v1/results/round_diff.json`: round two minus round one metrics.
- `data/golden_set/v1/results/judge_calibration.json`: qwen-plus vs qwen-max calibration sample.

Golden Set v1 evaluation `as_of` is `2026-07-09`. The frozen corpus contains
486 canonical recording files, 694 source rows, 510 unique source URLs, and
fingerprint `ef2d1fd2c414502140162508ef32838aaf8e4a56a6ab3678f9f57ed04f86960e`.
No cases were quarantined in the v1.0 freeze.

Run the current round runner against saved states or replay search:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/run_golden_round.py \
  --questions data/golden_set/v1/questions.json \
  --output data/golden_set/v1/results/round1.json \
  --work-dir _collab/006r3_recording-completion/round1 \
  --round-id round1 \
  --as-of 2026-07-09 \
  --ledger-path _collab/006r3_recording-completion/round_llm_ledger.jsonl \
  --judge-samples 3 \
  --state-path-map _collab/006r3_recording-completion/state_path_map.json
```

`--state-path-map` re-scores saved `ResearchState` artifacts without rerunning
Planner, Extractor, Reporter, or search. Omit it to run the full LLM pipeline
over frozen-corpus replay; that path is significantly slower for evidence-heavy
cases.

## Judge

Golden Set judge calls use the unified `LLMClient` with role `judge`; citation
support uses role `citation_support`. Both default to `openai/qwen3.7-plus` through
DashScope's OpenAI-compatible endpoint. Each full round uses three judge samples
per question and aggregates dimensions by median. The locked scoring dimensions
and weights are:

| Dimension | Weight |
| --- | ---: |
| `fact_coverage` | 0.35 |
| `fact_accuracy` | 0.25 |
| `citation_support` | 0.25 |
| `synthesis_balance` | 0.15 |

Prompt file: `prompts/judge.md`. Current prompt hash:
`2e87f85cb54673ab6f84e0f0fc4b8c108441757e20ecd9ec4c3416df5d893533`.

The historical qwen-plus vs qwen-max calibration sample over Q01-Q10 produced
dimension agreement rate <=0.1 of `0.4`, average dimension absolute difference
`0.3299`, and average weighted-score absolute difference `0.3362`. This is a
material judge-model sensitivity signal. Current operational judge calls use the
explicit `qwen3.7-plus` model name; PM review is still required before treating
Golden Set scores as stable product benchmarks.

## Golden Set v1 Results

| Metric | Round 1 | Round 2 | Delta |
| --- | ---: | ---: | ---: |
| avg weighted score | 0.6134 | 0.6177 | +0.0043 |
| avg fact coverage | 0.6806 | 0.6749 | -0.0057 |
| avg fact accuracy | 0.5950 | 0.5922 | -0.0028 |
| avg citation support | 0.5589 | 0.5789 | +0.0200 |
| avg synthesis balance | 0.5783 | 0.5917 | +0.0134 |
| avg citation support rate | 0.8104 | 0.8256 | +0.0152 |
| avg citation resolution rate | 0.6000 | 0.6000 | +0.0000 |

Both false-premise cases, Q08 and Q16, were classified as refuted in both rounds.
No code repair was applied between rounds because the round-one bad cases were
dominated by saved report quality and citation-support limitations rather than a
small, isolated mechanical defect.

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

Before a new live recording round, rotate `data/runtime/search_ledger.jsonl` to
the task collaboration directory and start a fresh runtime ledger. Tavily credit
guardrails are scoped to the current ledger file, not to all historical runs.
Only rows that actually attempted a Tavily API call count toward credit usage.
Rows refused by the guardrail are written with `refused=true` and
`credit_estimate=0`. The warning and hard-stop thresholds are configurable via
`DEEPRESEARCH_TAVILY_CREDIT_WARNING_THRESHOLD` and
`DEEPRESEARCH_TAVILY_CREDIT_HARD_THRESHOLD`; evaluation recording currently uses
450 and 520.

Recording `as_of` and evaluation `as_of` are separate facts. Recording `as_of`
is provenance metadata for when a source key was collected and may have multiple
values inside one frozen corpus. Evaluation `as_of` is a single run-level date
injected through `DEEPRESEARCH_AS_OF`; for Golden Set v1 it is the latest
recording date in the frozen corpus and controls freshness-sensitive rules.

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
