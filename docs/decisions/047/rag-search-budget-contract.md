# RAG search budget contract

## Decision

`RagSearchService` executes its lexical-plus-dense boundary through the existing
`RAG_SEARCH_TOOL_SPEC` and `ReliableToolExecutor`. The caller may supply the
workflow's `RunToolContext`; the service consumes one run-wide external search
allowance before starting the backend operation.

This makes timeout, total deadline, bounded retry, circuit state, and external
request budget apply to the registered `rag_search` capability rather than only
to its individual providers. A refusal returns an explicit empty result and
`DegradationEvent`; it never fabricates a retrieval hit. Strict replay accepts
the same context argument but remains offline and does not consume it.

## Mutation M6

The guard removed was the `run_context.consume_external_request("search",
tool="rag_search")` line in `RagSearchService.search`. With a zero-request
budget, `test_external_request_budget_refusal_returns_explicit_empty_degradation`
failed because a backend hit was returned instead of the required explicit
empty degradation. The unmodified guard was restored. The raw first-failure
output is retained in the ignored 047 mutation artifacts.

## Verification

The RAG unit and integration subset covers normal retrieval, timeout
degradation, explicit empty-index degradation, budget refusal, adversarial
evidence admission, and strict degraded replay. Full gate evidence is recorded
after the change.
