# T8 active-provider live result — INCOMPLETE

## Registered attempt

- Invocation commit: `4e6afcb`
- Workflow run id: `1bcf7c8c-fbf9-4d89-9a6e-60b435a39616`
- Frozen index version: `finance_v1-43f11085-heading_page_first_1024_256`
- Command exited 0 and produced a non-empty report, audit bundle, snapshot, and
  structured outputs. The report includes `audit_citation_closure: ok`.

## Successful observations

- Manifest has LLM, search and RAG actual fidelity `real`; their usage is 1, 8
  and 3 respectively.
- The required index version is present.
- The local RAG ledger has six embedding/rerank rows and local cost CNY
  `0.1281985`.
- Workflow manifest cost is CNY `0.13968028`.
- The registered budget ceilings did not trip.

## Why this remains incomplete

The original active-provider validator incorrectly accepted the manifest. The
manifest has three `structured_data_provider` degradation events, each an
AKShare symbol-resolution timeout, while its usage remained zero and fidelity
was `unused`. That is an attempted-and-failed optional provider, not a truly
unused provider. The repaired validator rejects the manifest with
`optional_provider_degradation.structured_data=3`.

The run also used the old fixed RAG ledger run id. Its generated report
therefore printed CNY `0.5253655`, aggregating previous runs sharing the index
id, instead of the local run's CNY `0.1281985`. Commit `115c703` now generates
a unique RAG ledger run id for every live invocation; this repair occurred
after the one authorized run and has not been used to claim a corrected result.

## Decision

No second paid run was made. Before a future run, the user must decide whether
an actually attempted but failed AKShare structured-data provider is allowed to
be optional for a 20-F research task. The recommended fail-closed policy is no:
either make the provider genuinely unused for this issuer or introduce a
compatible provider. A new authorization and preregistration are then required
to validate the unique-ledger repair and the selected policy.
