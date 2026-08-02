# 081 Correctness and accounting fixes

## Result

Blocks A, C, D, E, F, and G were implemented and the full local gate exited
zero. Block B is **INCOMPLETE**: `StructuredDataRecord.as_of` is still used as
both retrieval time and publication time in the structured-provider pipeline.
No schema migration or replay compatibility path was committed, so the required
freshness semantics cannot be claimed.

## Implemented changes

- A: only remove trailing zeroes from rendered values that have a decimal point;
  integer CNY values now retain their complete magnitude. The `元` difference is
  intentional: reporter uses ungrouped digits while grounded facts use grouped
  digits in its reader-facing section.
- C: record the second provider call when repair parsing fails, and read the
  subprocess result queue before joining to avoid a large successful payload
  producing a false timeout.
- D: reject unsafe literal-IP/file URLs before a request, manually bound
  redirects, apply content-type/size policy, standardize the owner token name,
  and use constant-time token comparison.
- E: calculate growth after normalizing compatible currency units; percentages
  are not comparable amount inputs.
- F: reject new calls when the shared executor is saturated and correct the
  non-daemon/atexit-join documentation.
- G: validate the RAG injection-guard invariant independently of the
  operational fail-fast flag and report it as an invariant error.

## Validation

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py`: exit 0.
- `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/check_domain_boundary.py`:
  `import_sites=0 literal_files=3 literal_hits=9 lexicon_terms=33`.

## Incomplete acceptance evidence

The required A–G mutation logs were not produced in this execution, and the
block-B date probe/demo/replay acceptance suite was not implemented. These are
not represented as passing evidence.
