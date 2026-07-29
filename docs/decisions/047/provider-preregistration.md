# 047: DashScope retrieval-provider preregistration

Date: 2026-07-29

## Registered experiment

Use DashScope `text-embedding-v4` at 1024 dimensions and `qwen3-rerank` for
the frozen `finance_v1` / `retrieval_v1` retrieval experiment. The hypothesis
is that cross-lingual dense retrieval plus reranking will outperform the
frozen Chinese lexical BM25 baseline. The decision rule remains unchanged:
do not perform paid tuning if the pre-registered test gate does not improve
nDCG@10 by at least 0.10, or if either absolute threshold fails.

The round plan authorizes ¥85 in total and a ¥50 maximum for the index-build
step. The first live request is a ten-chunk connectivity and response-contract
probe; it is charged through the shared `llm_ledger.jsonl` using the same
budget boundary as the eventual index run.

## Price and operating inputs

Public Model Studio documentation checked on 2026-07-29 gives the Beijing
list price as ¥0.5 per million input tokens for `qwen3-rerank`, and documents
`text-embedding-v4` at ¥0.0005 per 1K input tokens. The same documentation
states dimensions `2048, 1536, 1024, 768, 512, 256, 128, 64`, maximum ten
rows per request, and 8,192 tokens per row. This records a conservative
runtime rate of ¥0.5 per million input tokens for both probes.

Sources:

- https://help.aliyun.com/zh/model-studio/qwen3-rerank
- https://help.aliyun.com/en/model-studio/embedding-interfaces-compatible-with-openai

Account-specific discounts or free quotas are not claimed. Actual provider
usage tokens and the calculated cost remain in the shared ledger; an unexpected
cost or three retry-exhausted provider failures stops the paid path.
