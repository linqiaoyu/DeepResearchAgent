# 081 Correctness and accounting fixes

## Result

All blocks A–G were implemented and the full local gate exited zero.

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

## Completion update

- B adds `StructuredDataRecord.source_pub_date`; `as_of` is now retrieval
  provenance. SEC supplies filing dates, AKShare explicitly supplies none, and
  legacy trajectories deserialize to the same explicit-unknown state. Trajectory
  schema version is 6, while strict replay remains compatible with versions 3–5.
- All seven real mutation failures are retained under `_collab/081/evidence/`.
- The final full gate is retained as `_collab/081/evidence/gate.log` and exited
  zero after all source and test changes.
