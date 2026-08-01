# Rerank degradation is manifest-visible

## Decision

When `RagSearchService` takes the rerank fail-open path, it adds the resulting
`DegradationEvent` to the active `RunToolContext` as well as returning it in
`RetrievalTrace`. The workflow synchronizes that context before Reporter and
therefore writes the same event to `RunManifest.degradation_events`.

Strict replay rebuilds that event from the redacted recorded `rag_search`
status and reason. It remains offline: no embedding or rerank provider is
called. This preserves the final degradation notice and makes replayed output
match the recorded output.

## Mutation M13

The protected line is `run_context.degradation_events.append(degradation)` in
`RagSearchService.search`. Removing it caused the recorded run to omit the
rerank degradation while strict replay correctly reconstructed it, so the
integration test failed on the final-report mismatch. The raw first failure is
retained in the ignored 047 mutation artifacts. The line was restored.

## Verification

The RAG degraded-replay integration test writes a manifest, asserts its
`degradation_events` contains `rerank` / `timeout`, requires strict replay to
reproduce the report, and continues to prove the recorded Top-8 branch is
preserved without provider access.
