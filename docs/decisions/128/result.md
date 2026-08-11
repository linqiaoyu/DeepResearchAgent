# R128 — external-call closure

## Verdict

PASS. H04 is complete: all nine production LLM, Tool, RAG, and MCP provider
boundaries are registered; all nine carry timeout, retry, request-budget, and
explicit degradation evidence; all LLM SDK calls remain owned by `LLMClient`.

## Repairs

- Qdrant HTTP now passes through `ReliableToolExecutor`, a bounded `ToolSpec`,
  and `RunToolContext`. Each retry consumes external-request budget and failure
  is explicitly fail-closed while canonical storage remains authoritative.
- DashScope embedding and rerank HTTP attempts now consume the shared external
  request budget inside the retried operation.
- AKShare opaque SDK attempts now consume the workflow budget, including the
  non-isolated test/runtime path, and accept a new run context.
- External MCP calls now use a full `RunToolContext` and consume request budget
  only after paid-call authorization succeeds.
- `data/external_call_registry.json` and its gate-wired checker enumerate the
  complete production class in both directions and verify source evidence for
  all four controls.

## Falsification

A real production mutation added an unregistered file importing `httpx`. The
checker exited 1, named that exact file in the discovered set, and reported:

```text
{"controlled": 9, "coverage": 0.9, "discovered": 10, "llm_bypasses": 0, "registered": 9}
```

The mutation was removed. The self-test also rejects a missing registration,
missing timeout, wrong LLM gateway, missing source evidence, and a synthetic
new provider boundary.

## Verification before complete gate

- External-call self-test: PASS, 6 cases.
- Production measurement: discovered 9, registered 9, controlled 9, coverage
  1.0, LLM bypasses 0.
- Qdrant/RAG/MCP/structured-provider suites: 57 tests pass.
- Repository Ruff and scoped strict mypy: pass.
- An initial targeted unittest command omitted `tests` from `PYTHONPATH` and
  failed importing `support.timing`; the corrected `PYTHONPATH=src:tests`
  command passed. This was command construction, not a product failure.
- Paid or network calls: none.

## Test changes

New assertions prove that zero Qdrant and MCP request budgets reject before the
HTTP/remote call. Existing assertions, fixtures, and scoring contracts were not
weakened.
