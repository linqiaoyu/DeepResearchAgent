# T8 active-provider acceptance amendment

## User-approved scope change

The user authorized modifying the T8 corpus/provider acceptance design after
Round 061 demonstrated that the required Alibaba 20-F corpus issuer is not
compatible with the configured A-share AKShare structured-data provider.

## Decision

Retain raw manifest semantics: a run with an unused provider remains
`actual_realness=mixed`; no provider is relabelled. Add
`scripts/check_real_run_manifest.py --require-active-real` for the amended T8
acceptance:

- workflow LLM, web search, and RAG search must each have usage at least one
  and actual fidelity `real`;
- disclosure and structured data may be unused only when their usage is zero
  and their actual fidelity is exactly `unused`;
- if either optional provider is used, it must have actual fidelity `real`;
- raw manifest realness must be `mixed` if any optional provider is unused,
  otherwise `real`.

The old `--require-structured` and `--require-all-real` checks remain unchanged.

## Evidence

The Round 061 manifest passes the new validator and still fails the old
`--require-all-real` validator. Unit tests cover a passing active-provider
manifest and rejection of fixture RAG. Changing the active-provider fidelity
comparison from `real` to `fixture` makes the passing test fail; the raw output
is retained under the Round 062 evidence directory.

## Consequence

The Round 061 run cannot be retroactively claimed to include the subsequently
repaired report-level citation-closure output. A new paid run, fresh
preregistration, and explicit authorization remain required before T8 can close
under this amended acceptance.
