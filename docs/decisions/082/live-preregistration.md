# 082 live-run preregistration

## Registered execution baseline

- Execution commit: `ced017b1ec481902fbaaa1092cde533e45ed4acb`.
- Both live runs will execute from that exact commit in an isolated worktree.
- The commit adds only the offline fidelity probe and its tests; it does not alter
  the research workflow, provider selection, reporter, or audit-bundle behavior.

## Hypotheses and measurements

1. Both runs will be three-layer real executions: live LLM, live RAG retrieval
   against `data/runtime/047-assets.db`, and `sec_companyfacts` structured data.
2. The Chinese NIO question will cite no more RAG-corpus evidence than the English
   PDD question; cited-evidence and RAG-evidence counts will be recorded, not
   inferred from prose quality.
3. Both resulting packages will have zero footnote misreferences and zero
   magnitude mismatches under `scripts/check_082_report_fidelity.py`.

## Fixed runs

| Output | Topic | Language | as-of | depth |
|---|---|---|---|---:|
| `live-nio-zh` | 蔚来 2024 年年报的营收与毛利情况 | Chinese | 2026-07-01 | 1 |
| `live-pdd-en` | PDD 2024 annual report revenue and gross margin | English | 2026-07-01 | 1 |

Both commands use `--mode live --allow-paid-api`, RAG database
`data/runtime/047-assets.db`, index version
`finance_v1-43f11085-heading_page_first_1024_256`, and
`DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=sec_companyfacts`.

## Budget, decision, and rollback rules

- Single-run circuit breaker: CNY 15.00; two-run total circuit breaker: CNY 20.00.
- If a provider layer falls back to fixture, label the run `mixed` and identify the
  downgraded layer; do not call it real.
- If a run fails from environment or command construction, preserve its output and
  use at most one third-run retry. No retry is permitted to select a better result.
- If either circuit breaker triggers, stop live execution, preserve the ledgers and
  report the incomplete result. No code or parameter changes will be made after
  this preregistration to improve a live outcome.
