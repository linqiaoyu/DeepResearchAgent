# T8 retry-stop live validation preregistration

Date: 2026-08-02

## Authorization and hypothesis

The user authorized one T8 paid attempt up to CNY 15 and a CNY 20 round
ceiling. R069 established that a real LiteLLM child can be reaped at its
deadline, but exposed that retry exhaustion could still degrade to a fallback.
Commit `b655c84` now propagates retry exhaustion in live engines. This is a
new experiment on a new code revision.

Hypothesis: one bounded real run completes with all three provider layers real,
RAG participates, and the package delivers a non-empty report with a complete
manifest.

## Frozen configuration

- topic: `阿里巴巴 2024 年 20-F 财务表现与风险因素研究`
- as-of: `2026-07-01`; depth: `1`
- structured-data provider: `sec_companyfacts`
- RAG database: `data/runtime/047-assets.db`
- RAG index: `finance_v1-43f11085-heading_page_first_1024_256`
- mode: `live`, with `--allow-paid-api`
- workflow LLM cap: CNY 3; RAG cap: CNY 12; total cap: CNY 15

## Measures and decision rule

The run passes only if the output report is non-empty; the final manifest says
`actual_realness=real` and carries the requested retrieval index; the RAG
ledger contains an embedding or rerank row; total recorded cost is at most CNY
15; and the delivered report contains `audit_citation_closure`.

Stop the paid command immediately on retry exhaustion, any cost breaker,
provider failure, or delivery failure. Do not rerun on this authorization if
the command stops or fails. Preserve the command output and all accounting;
any subsequent execution needs fresh authorization and preregistration.
