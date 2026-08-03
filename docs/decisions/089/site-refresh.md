# 089 static-site design restoration and content refresh

Status: accepted for the static showcase update.

## Decision

Restore the multi-page visual system from commit `cfca7fb` and keep its
stylesheet byte-for-byte stable. Update reader-visible content to the current
Round 087 result: the final Chinese NIO and English PDD reports, the frozen
60-document SEC 20-F corpus, the finance-SUT-only scope, the eight-pair live
A/B decision, and the final manifest/citation checks.

The old RAG release-evidence file referenced by the restored builder is no
longer present in the current repository. The RAG page therefore states current
defaults and limits instead of re-publishing unavailable historical metrics.

## Guard

`scripts/gate.py` now builds the static site and checks that its Round 087 facts
are present and that the generated stylesheet matches the `cfca7fb` baseline.
A mutation that removes a required live-validation fact fails the checker.
