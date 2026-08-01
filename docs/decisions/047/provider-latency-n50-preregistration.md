# Provider latency N=50 preregistration

This registered measurement records real DashScope embedding and rerank latency
only. It is not a retrieval evaluation: it writes no result under the frozen
test dataset and changes no index, chunker, or search parameter.

- Samples: exactly 50 embedding calls and 50 rerank calls.
- Inputs: local authority chunks, truncated to 512 characters for the rerank
  request; neither chunk text nor credentials are persisted in the result.
- Accounting: the existing shared `llm_ledger.jsonl`, run ID
  `047-provider-latency-n50`, provider budget ¥12; a ledger budget exception
  stops the item and remains recorded.
- Measurements: p50/p95 latency and CNY cost for both provider boundaries.
- Decision: descriptive only; no threshold and no parameter change follow from
  the result.
