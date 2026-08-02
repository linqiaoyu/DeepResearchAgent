# T8 retry-exhaustion live result

## Run record

- Date: 2026-08-02
- Commit at execution: `03edf13`
- Research run id: `5a5e82c6-0706-4fcf-a7f1-5858fd1a7ad3`
- Configuration: Alibaba 2024 20-F topic, as-of `2026-07-01`, depth 1,
  `sec_companyfacts`, live LLM/search/RAG, database
  `data/runtime/047-assets.db`, index
  `finance_v1-43f11085-heading_page_first_1024_256`.

## Result

Planner, real search, embedding, and rerank ran. The extractor received 28
sources, then its three 60-second provider attempts exhausted. It raised
`LLMRetryExhaustedError` at the extractor node and the workflow stopped. The
raw trace has exactly three extractor LiteLLM starts after the extractor node
started, with no fourth start. No report was delivered.

Recorded workflow LLM cost was CNY 0.00407748; RAG ledger cost was CNY
0.102626; total recorded cost was CNY 0.10670348, under the CNY 15 cap.

## Decision

R071 is INCOMPLETE for T8 acceptance. It establishes that the retry-exhaustion
stop rule works in the real path, but not a successful E2E delivery. The
provider's inability to process the extractor request inside the 60-second
bound needs a separately scoped design/fix before a new paid experiment.
