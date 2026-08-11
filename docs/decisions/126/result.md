# R126 — split Harness H2 from finance product acceptance

## Verdict

PASS. Harness mechanism readiness and finance-product effectiveness now have
separate machine-readable contracts. This round does not claim that any newly
registered Agent technology is H2-ready: all twelve start at `wired`, and R150
will fail the complete gate unless every one carries a published numeric proof.

## Contract change

- `data/harness_acceptance.json` freezes twelve technology families, their
  numeric H2 criteria, a three-state vocabulary (`absent / wired / h2_ready`),
  and an R150 proof deadline.
- `scripts/check_harness_acceptance.py` checks the technology set in both
  directions, freezes every metric/operator/target in code, validates published
  proof metrics, and rejects an arrived deadline with any non-H2 family.
- The finance proof moves from R140 to R160. Its 30-case cohort, three-layer
  live fidelity, three reader-visible thresholds, and no-best-of rule are
  unchanged.
- The nine default-off capability decisions move to R151–R158, after the H2
  deadline and before the finance proof. Their graduation criteria are
  unchanged.

This one-time deadline migration is the explicit delivery-order decision:
mechanisms must become safe and reproducible before their finance defaults are
selected. It is an evaluation-contract change and is recorded in
`docs/evaluation.md` rather than represented as nine capability deferrals.

## Falsification

The H2 guard self-test rejects five classes: a missing technology, a moved R150
deadline, a weakened numeric target, an H2 status without proof, and the R150
deadline arriving while technologies remain merely wired. A direct mutation
deleting `tool_calling` produced:

```text
technologies must be exactly ['content_security', 'mcp', 'memory', 'observability_replay', 'orchestration', 'planning_replanning', 'rag', 'reflection', 'skills', 'storage_backends', 'tool_calling', 'tool_use'], got ['content_security', 'mcp', 'memory', 'observability_replay', 'orchestration', 'planning_replanning', 'rag', 'reflection', 'skills', 'storage_backends', 'tool_use']
```

## Verification

- Harness acceptance: `PASS cases=5`, registered `12/12`, H2-ready `0`.
- Product acceptance: `PASS cases=6`, target R160, proof absent as expected.
- Capability graduation: `PASS cases=9`, nine pending decisions due R151–R158.
- Guard wiring: 29 guards, 29 wired, 0 unwired.
- Complete gate: 1173 tests, 7 declared skips, 0 undeclared skips; Ruff and
  scoped strict mypy pass; deterministic demo/eval pass; tracked files
  unchanged.
- Paid or network calls: none.

## Remaining gap

R150 currently has twelve missing H2 proofs by design. The next rounds must
change measured technology behavior and publish proof; changing `wired` to
`h2_ready` without those metrics is rejected.
