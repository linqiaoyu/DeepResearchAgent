# 047 stage-0 diagnosis and issuer-alias decontamination

The frozen B5-5 result remains a FAIL. Stage 0 rules out an index identity
failure: 20/20 stored vectors returned their labelled chunks at rank 1. The
authorized capped embedding probe found every measured Chinese and English gold
rank above 100 (the table question was absent from top 500), and `text_type=query`
was identical to omission. Together with the existing table-content probe
(`all_three_count=0` of 5), this supports a chunk-content diagnosis, not the
prior unverified cross-language explanation. No corpus, label, chunker, index,
or threshold changed. A content repair would require a new index and the
separately estimated ¥13.80 rebuild, which was not run.

`QdrantIndex.query()` calls `ensure_collection()` at
`src/deepresearch_agent/rag/qdrant_index.py:157`; it PUTs payload indexes at
lines 92–105. The diagnosis therefore used direct read-only scroll/search POSTs.
The line-34 10-second default is also below the recorded 33.59-second cold start.
Neither production behavior was changed here.

The old `SEC_20F_ISSUER_ALIASES` was a handwritten 20-item evaluation-shaped
table added after a failed test. It is replaced by 60/60 filing registrant names
joined mechanically to a public Wikidata CC0 snapshot: 114 entities, 114
non-corpus entities under exact-name counting, 13/20 joined issuers, and zero
accepted ambiguous pairs. Low coverage was not hand-filled. The corrected
Wikidata query returned HTTP 403 here, so the committed asset is derived from
the existing public raw snapshot and records the corrected no-HQ query. Earlier
work incorrectly conflated Wikipedia CC-BY-SA with Wikidata CC0 and paused
unrelated work; that was an erroneous blocker.

Static aliases are not the B5-5 remedy. The future route is provider-bound
query-side entity linking/translation; aliases are only an offline cache. Also,
`_collab/047/prompt.md` is an insufficient historical task card; no history was
fabricated to repair that debt.
