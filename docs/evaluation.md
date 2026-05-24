# Evaluation Harness

The harness treats evaluation as a first-class subsystem, not a screenshot.

## Metrics

- `task_success_rate`: report generated with at least one evidence record
- `citation_accuracy`: citation markers in the report map to existing evidence rows
- `critic_catch_rate`: Critic found seeded or naturally occurring quality issues
- `answer_relevance`: topic terms appear in the final report
- `faithfulness`: bullet claims in the report carry citations
- `cost_usd`, `latency_seconds`, `token_used`: operational metrics for Pareto analysis

## Golden Questions

`data/eval_set.jsonl` contains 50 cases covering financial AI, wealth management, citation verification, Evidence Store design, Critic loops, checkpointing, Docker deployment, and interview packaging.

Run:

```bash
PYTHONPATH=src python scripts/run_eval.py --limit 5
```

The command writes `artifacts/evaluation/latest_metrics.json`.

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
- The output includes quality, citation, cost, latency, and token fields.
- Critic issues are visible in the Streamlit dashboard and final report.

