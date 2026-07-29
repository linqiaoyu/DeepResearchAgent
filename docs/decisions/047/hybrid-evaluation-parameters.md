# 047 hybrid retrieval evaluation parameters

Frozen before the single test-split evaluation on 2026-07-29.

- Corpus fingerprint: `43f1108577d5c3a56f9daeb1d9c942b985a73759fce7d11e374831c67c0badb5`
- Index version: `finance_v1-43f11085-heading_page_first_1024_256`
- Embedding model: `text-embedding-v4` (1024 dimensions)
- Rerank model: `qwen3-rerank`
- Retrieval sequence: BM25 plus dense, RRF Top-50, rerank Top-8
- Evaluation code commits: `aa652fc`, `0eb3157`, `e4fc8f4`, `cef4e44`

The completed dev run used 24 answerable questions.  Its Recall@20 was
0.10416666666666667, RRF nDCG@10 was 0.008515933232853589, and rerank
nDCG@10 was 0.043490471214667724.  These values are recorded as diagnosis,
not used to alter the frozen parameters.  The next test-split run is the only
test execution for this code and parameter set.

The dev ledger records ¥5.859141 of actual provider cost across 217 calls.
That includes unsuccessful cost-guard attempts and calls made before a
runtime interruption could persist a checkpoint; the completed per-question
result itself contains no duplicate question rows.
