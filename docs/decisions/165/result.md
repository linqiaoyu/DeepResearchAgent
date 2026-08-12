# R165 — F14 product acceptance proof

## Decision

**PRODUCT ACCEPTANCE PASSED.** The independent R165 candidate executed the
immutable 30-question cohort exactly once on code commit `0786757`, using six
fixed, isolated ledger authorities and at most four concurrent shards. It did
not load saved states, rerun failed questions, select best cases, or splice any
R160/R162/R164 result. All 30 cases reached `status=done`, and LLM, retrieval,
and structured-data fidelity were all `live` in the same merged runner JSON.

The machine-recomputed product metrics are:

- `evidence_reachable_rate = 1671 / 2221 = 0.7523638001` (target `>= 0.60`);
- `orphaned_sub_questions = 0` (target `== 0`);
- `false_premise_failed = 0` (target `== 0`).

`data/product_acceptance.json` therefore points to
`docs/decisions/165/product-proof.json` as the sole product proof. The
published JSON is byte-identical to the ignored merged artifact at
`artifacts/165/product-candidate.json`, with SHA-256
`c56e1eb462d7e2e8142efe3a5bcde9a100f40bff1fcf905e6d0877330d2392ba`.

## Reliability and cost

- Coverage: 30/30 expected, 30 scored, 30 done; errors and structured failures: 0.
- Planner timeouts, shared-ledger collisions, and silent exclusions: 0.
- Generation cost: CNY 9.02516788; judge cost: CNY 4.35360600; total:
  CNY 13.37877388, below the preregistered CNY 25 round fuse.
- Plan spend through R165: CNY 52.29709726, below the CNY 300 total fuse.
- One initial shard-5 command failed during argument parsing because
  `--question-ids` was passed as separate values. It made no provider call and
  created no case result; the corrected comma-separated command then ran the
  preregistered Q21–Q25 shard exactly once.

## Provider rollover boundary

R164 had established that the prior Tavily account was quota-exhausted: its
calls returned HTTP 432, while a redacted probe using the user-authorized
replacement returned HTTP 200 and a non-empty result. Only after that
confirmation was the ignored `.env` value changed. R165 showed successful live
search/fetch calls and no renewed quota-exhaustion pattern. No credential value
is stored in source, decisions, reports, logs, or the product proof.

## Verification and next route

`scripts/check_product_acceptance.py` reads the published runner JSON and
recomputes all three thresholds rather than trusting claimed summary metrics.
Its self-test rejects six contract mutations. With F14 passing on its first
post-provider-repair independent candidate, no further full 30-question run is
permitted or needed. Work proceeds directly to provider-free F15 closure.
