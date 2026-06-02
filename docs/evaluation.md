# Evaluation Harness

The harness treats evaluation as a first-class subsystem, not a screenshot.

## Metrics

- `task_success_rate`: report generated with at least one evidence record
- `citation_accuracy`: citation markers in bullet claims map to Evidence rows and the cited claim has deterministic text overlap with `Evidence.claim` or `Evidence.extract_text`
- `critic_catch_rate`: MVP heuristic/proxy for whether the Critic exposed quality issues. Current deterministic logic scores visible issue coverage, using `min(1.0, len(issues) / 3)` when issues are present and `1.0` when no issues are found. It is not true seeded issue recall or human-labeled Critic recall.
- `answer_relevance`: topic terms appear in the final report
- `faithfulness`: bullet claims in the report carry citations
- `cost_usd`, `latency_seconds`, `token_used`: operational metrics for Pareto analysis

Unsupported or invalid bullet citations are counted as `citation_error` bad cases.

Production version: compute true critic recall from seeded issues or manually labeled bad cases.

## Golden Questions

`data/eval_set.jsonl` contains 50 cases covering financial AI, wealth management, citation verification, Evidence Store design, Critic loops, checkpointing, Docker deployment, and interview packaging.

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
`avg_faithfulness`, `avg_critic_catch_rate`, and total bad-case count.
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
- outdated source
- missing counterargument
- unverified projection

## Acceptance Criteria

- Evaluation can be run repeatedly from the command line.
- The output includes quality, citation, cost, latency, token, Critic catch rate, and aggregated bad-case fields.
- Critic issues are visible in the Streamlit dashboard and final report.
