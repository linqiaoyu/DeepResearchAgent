# T4b preregistration: paid production hybrid retrieval evaluation

## Authorization and hypothesis

User authorization was received for the task-card T4b paid path. Hypothesis: production entity
filtering plus issuer-alias expansion improves dev Recall@20 over the prior bare-pipeline 0.0128.

## Measurement and decision rule

Run the dev split once with the frozen production configuration. Only if dev Recall@20 is at least
0.10 may a separate test-split authorization be sought; otherwise stop the paid path and retain the
negative result for the golden-v2/pipeline decision.

## Cost and stop conditions

Budget estimate: 24 query embeddings plus reranking, ≤ ¥0.5. Single-run and aggregate circuit
breaker: ¥2. Stop immediately when any provider exhausts three retries, the ledger reaches ¥2, or
the Qdrant index is unavailable. No rerun or parameter tuning is permitted for this code version.
