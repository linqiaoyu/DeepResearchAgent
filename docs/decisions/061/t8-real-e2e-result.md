# T8 real three-layer E2E retry result — INCOMPLETE

## Registered attempt

- Time: 2026-08-02 02:04:54Z to 02:14:39Z (about 585 seconds)
- Code at invocation: `328d0a2 docs(eval): preregister final t8 retry`
- Workflow run id: `6d4eba6f-9818-4b9b-9da7-051a904c6ad2`
- RAG ledger run id: `rag-e2e-finance_v1-43f11085-heading_page_first_1024_256`
- Topic: 阿里巴巴 2024 年 20-F 财务表现与风险因素研究
- `as_of`: 2026-07-01; depth 1
- Index version: `finance_v1-43f11085-heading_page_first_1024_256`
- Mode: live, with the authorized CNY 15 per-attempt and CNY 20 whole-round
  circuit breakers.

## Observed result

The command exited 0 and wrote a non-empty report, structured outputs, audit
bundle, snapshot, and manifest. `audit_citation_closure=ok` was printed by the
package command. The manifest recorded the requested index version, three RAG
uses, six RAG embedding/rerank ledger rows, and no degradation events.

The result does not satisfy T8: `actual_realness` is `mixed`, not `real`.
`check_real_run_manifest.py --require-all-real` failed because the live plan
used neither structured data nor disclosure:

- `provider_usage.structured_data=0`,
  `actual_provider_fidelity.structured_data=unused`, and zero records;
- `provider_usage.disclosure=0`,
  `actual_provider_fidelity.disclosure=unused`;
- consequently `actual_realness=mixed`.

This is a fail-closed result, not a relabelling opportunity. The fixed topic is
an Alibaba 20-F question while the configured real structured provider is
AKShare, whose contract is for A-share data. The planner therefore generated no
structured-data requests. A successful three-layer T8 requires an explicit
product decision that reconciles the in-corpus issuer set with a compatible
real structured-data provider, or changes the acceptance configuration. Neither
choice is within this task's small script-only scope.

## Cost and timing

- Workflow LLM ledger total: CNY `0.12337276`.
- RAG ledger total: CNY `0.101933`.
- Combined observed total: CNY `0.22530576`.
- Both the workflow CNY 3 and RAG CNY 12 sub-budgets, and the CNY 15 / CNY 20
  registered circuit breakers, remained untripped.

## Post-run adjacent repair

The successful command printed `audit_citation_closure=ok`, but its generated
report did not contain the value. Commit `500ceca` now appends that value after
audit-bundle export and tests the delivered report. A mutation that removes the
append fails; its raw output is in the Round 061 evidence directory. This code
repair occurred after the only authorized live run, so it has not been used to
claim a repaired T8 result.

## Decision

No second paid run was made. T8 remains INCOMPLETE. A future attempt requires
both a new authorization and a user-approved resolution of the issuer/provider
compatibility conflict, followed by a new preregistration.
