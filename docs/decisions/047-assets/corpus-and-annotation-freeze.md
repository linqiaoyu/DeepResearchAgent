# 047-assets: finance_v1 corpus and retrieval_v1 annotation freeze

Date: 2026-07-29

## Decision

Freeze `finance_v1` as 60 official SEC EDGAR annual-report originals for 20
Chinese public issuers, with each issuer represented for fiscal 2022, 2023,
and 2024. SEC EDGAR HTML is a primary public filing archive and is used here
because each original is directly retrievable from a stable canonical archive
URL without a paid API or third-party mirror.

The corpus manifest is content-addressed and the downloader accepts only its
declared URLs. The current ingestion coordinate system is retained: global
extracted-text character offsets, with no chunk IDs in labels. Official HTML
has no intrinsic page number, so HTML audit rows carry a null page number and
the global coordinates plus exact excerpt are authoritative.

`retrieval_v1` has 60 frozen Chinese questions: 20 numeric, 15 table, 15
cross-period, and 10 refusal questions, split 24 development / 36 test. Its
annotations were drafted and self-reviewed by Codex using two passes. They are
not human annotations; `human_verified` remains false pending review of the
generated review packet.

## Consequences

- Chunking uses a 1024-token-equivalent, 256-token-equivalent overlap to keep
  the 60-original corpus at 22,953 chunks, inside the 20,000--30,000 target.
- Ingest output now carries exact `added_chunks` and `removed_chunks`, making
  a repeated ingest's zero diff executable evidence rather than an inference.
- The validator rejects document integrity errors, split/type contract drift,
  non-overlapping spans, audit excerpt mismatches, and fingerprint drift.
- A future corpus replacement needs a new manifest/version and a new label
  set; it must not rewrite this frozen set after test evaluation.
