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

## Observed probes

The first embedding contract probe returned ten 1024-dimensional vectors for
ten real-corpus chunks (11,273 input tokens, ¥0.0056365, 2.425 seconds).
The registered 200-chunk probe then completed in twenty ten-item calls:
213,354 input tokens, ¥0.106677, latency p50 2,255.5 ms, and p95 6,825 ms.
The rerank probe completed three queries with fifty candidates each, returned
fifty scored candidates per query, and recorded 169,085 input tokens,
¥0.0845425, p50 1,852 ms, and p95 1,948 ms.

The probe confirms the public endpoint and 1024-dimensional response contract.
It does not establish an account-specific rate-limit threshold or the provider's
maximum rerank candidate count; those remain explicit inputs to the full index
and evaluation run rather than being inferred from a successful 50-candidate
request.

## Full index and frozen quality experiment

The authorized full rebuild completed against the real `finance_v1` corpus.
The Qdrant collection contains 22,953 payload-only points, matching the 22,953
ready authoritative chunks; no unresolvable chunk was dropped. The aggregate
embedding ledger records 2,417 calls, 27,594,827 input tokens, and ¥13.797413
of calculated cost. One 32-way concurrency attempt received a real 429 and
stopped; the completed rebuild used bounded 16-way windows and checkpointed
each completed batch before any later error could lose it.

The frozen test split was then evaluated exactly once after parameters were
committed in `hybrid-evaluation-parameters.md`. It produced Recall@20
0.01282051282051282, RRF nDCG@10 0.0, and hybrid-plus-rerank nDCG@10 0.0.
This fails every B5-5 acceptance threshold. The outcome is a negative result,
not an availability failure, and the preregistered rule therefore forbids paid
parameter tuning or a replacement test run.

An explicit real RAG E2E package was added after the quality experiment. Its
first attempt completed the real planner call but the local execution carrier
ended before any RAG request, report, or RAG ledger row was written. It is not
reported as a three-provider E2E result.

Before a replacement attempt, the package runner was corrected so its separate
RAG adapter receives at most ¥12 while the workflow LLM client retains its ¥3
hard limit. The combined single-run ceiling is therefore the registered ¥15,
not two independent ¥15 allowances.

The first direct real retrieval probe exposed a product defect: the workflow
did not pass its configured `index_version` to `rag_search`, so Qdrant correctly
rejected the unversioned request. Commit `4e14754` binds the configured index
version at service composition. The repaired one-query probe completed
embedding and rerank with 50 lexical candidates, 50 dense candidates, 50 RRF
candidates, and 8 delivered candidates; `dropped_unresolvable=0`. All eight
delivered entries had a canonical URL, document version, and character range.
Its actual provider cost was ¥0.0458275 (one embedding and one rerank call).
This is retrieval-chain evidence only, not a replacement for the failed frozen
quality test or the incomplete three-provider E2E experiment.
