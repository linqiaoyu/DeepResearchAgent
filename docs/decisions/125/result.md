# R125 — rules that finish

## Verdict

PASS. The seven governance defects in the task card are repaired as contracts,
not as another round note. This round does **not** claim that the finance product
already meets its new completion target. It gives that claim one fixed,
machine-checked definition and a deadline.

## What changed

1. Every content-affecting flag that currently ships false is now present in
   `data/capability_graduation.json`: **9/9**, not the seven named from memory in
   the original audit. Each has a numeric criterion, a command, an initial
   decision round, and at most two four-round deferrals. The first deadline is
   R128 and the last is R138. Moving a deadline without recording a deferral is
   a failing mutation.
2. Product completion is one 30-question, three-layer-live cohort, with no
   best-of or cross-round splicing: evidence reachable by the reader >= 0.60,
   orphaned sub-questions = 0, and false-premise failures = 0. R140 is fixed in
   code. A proof must point to a published runner JSON; the guard recomputes the
   three metrics instead of trusting a handwritten summary.
3. `run_golden_round.py` now persists `provider_fidelity` in its JSON. This was
   the first downstream defect exposed when the new proof reader was exercised:
   the runner printed fidelity but did not store it. Saved-state runs are not
   accepted as product-completion proof.
4. Paid experiments must buy the preregistered statistical power before they
   start. A fixed cheap breaker can no longer authorise an n=1 experiment that
   the noise rule then forbids interpreting. This remains review-enforced
   because provider price and variance are experiment-specific.
5. `scripts/check_guard_wiring.py` makes all check scripts transitively
   reachable from gate, CI, or tests. **16** unwired round-local probes and one
   generic unused helper were removed rather than preserved as false coverage.
   Current result: **28 guards, 28 wired, 0 unwired**.
6. The misleading “self-built harness” statement now says exactly what is
   self-built (contracts, budgets, observability) and what is not (the LangGraph
   graph runtime). Numbered sections are exactly 1..11; both claims are mutation
   tested by `check_agent_guidance.py`.
7. Decision rounds are now an explicit, narrow round type: they must terminate
   one due capability with adequately powered evidence and do not add another
   guard. Guard retirement is explicit instead of append-only.
8. The formerly unwired module-size guard is in the gate and discovers every
   workflow/RAG module automatically. `engine.py` was split from 983 lines to
   **781**, with the 228-line cohesive run-persistence mixin below the 600-line
   extracted-module limit. The limit was not raised.

## Tests changed and why

- `tests/unit/test_golden_round_fidelity.py`: added a contract for the structured
  fidelity mapping now persisted with every scored round.
- `tests/unit/test_run_manifest.py`: moved the manifest-writer fault injection to
  `workflow.run_persistence`, the actual call site after the cohesive extraction.
  The assertion itself was not weakened; it again proves a manifest disk failure
  degrades without losing a completed run.

No golden question, truth, scoring rule, snapshot, skip, or assertion was
weakened or removed. Deleted check scripts were not tests and were executed by
no runner; their live invariants remain covered by the 1173-test suite and the
current named guards.

## Falsification evidence

The new self-tests reject these deliberate wrong implementations:

- orphan guard and dangling runner reference;
- unregistered/stale default-off flag, arrived deadline, vague criterion,
  missing measurement, third deferral, silent deadline move, and opt-in without
  reason/proof;
- fixture provider in a product proof, missing metric, lowered 0.60 target,
  moved R140 deadline, arrived deadline without proof, and empty proof;
- swapped AGENTS sections and the false “self-built graph runtime” claim.

Initial real failures preserved in the ignored R125 report include
`unwired=11`, missing `data/capability_graduation.json`, and the manifest fault
injection patching the pre-extraction module. After repair all of the mutations
above are rejected and the repository itself is clean.

## Verification

- Targeted persistence/fidelity/budget suite: **67 tests, 0 failures**.
- Complete gate: **1173 tests**, **7 declared skips**, **0 undeclared skips**.
- Ruff: pass. Strict scoped mypy: pass.
- Deterministic demo: task success 1.0, citation resolution 1.0, uncited claim
  rate 0.0; reference list pass.
- Deterministic five-case eval smoke: baseline comparison pass.
- Tracked-files-unchanged: pass.
- Paid/network experiments: none. This round changes experiment eligibility;
  it does not spend money on an underpowered validation.

## First downstream paths truly exercised this round

- proof JSON fidelity persistence and saved-state rejection;
- manifest-write failure after the persistence mixin extraction;
- successful, budget-exhausted, and failed-run sidecar paths;
- episodic and procedural cross-run memory writes after extraction;
- transitive guard reachability and dangling-reference detection.

## Remaining measured gap

The product target is intentionally not marked achieved: the latest measured
fully-live baseline remains R116's evidence reachable rate of 0.27, below 0.60.
The point of R125 is that this gap can no longer disappear behind green
anti-regression gates: capability decisions begin expiring at R128 and the
product proof expires at R140.
