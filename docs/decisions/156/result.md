# R156 / F08 — Capability combination pre-screen

## Decision

PASS. All nine default-off Agent capabilities now have a machine-readable
candidate decision. None qualifies for a paid F09 paired experiment, so all
nine are permanent opt-in and the graduation registry has zero pending entries.
This is a finance-default decision, not a statement that the H2 mechanisms are
absent or broken.

The decision follows the preregistered filter: a capability must have both a
specific causal path to one of the three frozen product metrics and an
affordable powered design. MCP and the injection guard have no registered
product-metric hypothesis. Prior and procedural memory require cross-run state,
which F14 forbids. The default reflection reasoner has no finance action policy.
The observed orphan was repaired downstream without another research
iteration. Model-selected tool calls target no missing tool class in F01.
Skills lack a metric-normalization failure census.

RAG is the strongest apparent candidate, but its shipped index contains 60 SEC
filings for 20 US-listed issuers and has zero direct company overlap with the 14
named companies in the frozen cohort. Paying for an A/B run would demonstrate
activity on a corpus mismatch, not cohort-wide financial quality. It therefore
also remains explicit opt-in until a product-relevant corpus is separately
authorized.

## Evidence and boundary

- `data/capability_prescreen.json` records 9/9 decisions, zero paid candidates,
  zero full-cohort authorization, and CNY 0 cost.
- `scripts/check_capability_prescreen.py` derives the RAG scope from the shipped
  corpus and frozen questions, and cross-checks every permanent opt-in against
  `data/capability_graduation.json`.
- Two real mutations—falsifying corpus overlap and reverting Reflection to
  pending—both exit 1.
- The graduation self-test now supports the achieved `pending=0` lifecycle
  instead of crashing because it assumed unfinished work must always exist.

No provider call, golden-truth change, product-threshold change, full cohort,
or remote write occurred. Round cost is CNY 0.

The final local gate passed with 1,221 tests, 7 registered skips, 59/59 guards
wired, and tracked files unchanged. Before that, one targeted command named the
nonexistent module `tests.unit.test_capability_graduation` and failed with one
`ModuleNotFoundError`; the corrected existing capability-invariants suite ran
5/5 successfully. This was a command-construction error and is retained rather
than presented as a product failure.
