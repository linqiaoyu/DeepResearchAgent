# T4b paid dev result

Prerequisite Qdrant collection status was `exists`. One production-configured dev execution used
entity/period filters and alias expansion with index
`finance_v1-43f11085-heading_page_first_1024_256`.

Result: Recall@20=0.0972222222, RRF nDCG@10=0.0110028384, rerank nDCG@10=0.1317030716,
24 answerable questions and zero unresolved-relevant cases. The experiment made 48 provider calls
(embedding/rerank) costing ¥1.1137635, below the ¥2 circuit breaker.

The preregistered Recall@20 ≥ 0.10 threshold was not met. The paid path stops here: no test-split
run, no parameter changes, and no rerun are authorized by this result.
