# T8 real E2E post-environment-repair result — INCOMPLETE

Date: 2026-08-02
Commit: `fcb54fa` at preregistration; source tree unchanged during the live
attempt.

## Attempt

One live attempt was made under the committed preregistration:

- Workflow research id: `9b997701-756a-495c-882e-a485533d6255`
- RAG ledger run id: `rag-e2e-finance_v1-43f11085-heading_page_first_1024_256`
- Index: `finance_v1-43f11085-heading_page_first_1024_256`
- Topic/as-of/depth: Alibaba 2024 20-F financial performance and risk factors;
  `2026-07-01`; 1.

The workflow itself reached `status=done`, produced a manifest, and made real
LLM, search, embedding, and rerank calls. Its manifest nevertheless reports
`actual_realness: mixed`, not `real`: both requested structured-data operations
degraded after AKShare symbol resolution timed out at 15 seconds. A web-fetch
timeout also appears in its degradation events.

After the workflow completed, `scripts/run_research_package.py` failed while
writing its report:

```text
KeyError: 'cost_cny_total'
```

`LLMClient.aggregate_run()` supplies `total_cost_cny`; the script read the
wrong key. Consequently no `report.md` was written and the package cannot
satisfy T8's report, citation-closure, or realness acceptance criteria.

## Cost and result

- Workflow ledger: CNY 0.12140068 (6 rows)
- RAG ledger: CNY 0.101267 (6 rows; embedding and rerank present)
- Reconciled observed total: **CNY 0.22266768**
- Per-attempt cap: CNY 15; whole-round cap: CNY 20
- Result: **INCOMPLETE**

No second paid run was made. A subsequent attempt requires fresh authorization
because it would use a repaired code version. The repair must address the
incorrect RAG aggregate key and should also investigate the structured-data
timeout before claiming all-three-layer realness.
