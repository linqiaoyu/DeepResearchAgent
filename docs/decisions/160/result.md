# R160 — F14 first full product acceptance candidate

## Decision

**PRODUCT ACCEPTANCE FAILED.** The sole planned full 30-question candidate ran
the frozen cohort exactly once on commit `a487a75`, with six isolated ledger
authorities, no saved states, no reruns, and no best-of or cross-run splicing.
All 30 cases reached `status=done` and all three provider layers reported live
fidelity. The candidate passed two product thresholds but failed the third:

- `evidence_reachable_rate = 2333 / 3089 = 0.7552606021` (target `>= 0.60`);
- `orphaned_sub_questions = 0` (target `== 0`);
- `false_premise_failed = 1`, Q16 (target `== 0`).

The product acceptance registry therefore remains without proof. This result
must not be relabelled, superseded on unchanged code, or combined with a later
candidate. Per the preregistered rule, Q16 routes one defect class to conditional
F13: the Reporter adopted a false premise even though its selected evidence
contained the contrary 2024 ranking and figures.

## Reliability and cost

- Coverage and terminal status: 30/30 done; errors and silent exclusions: 0.
- Planner timeouts, ledger collisions and budget rejections: 0.
- Q13 and Q21 both completed on the R159 budget-aware scheduling code.
- Generation cost: CNY 9.43304612; judge cost: CNY 5.12665480; total:
  CNY 14.55970092, below the CNY 48 round fuse.
- Tavily quota-exhaustion responses: 0; replacement-key activation: 0.

## Evidence and next route

`failed-product-candidate.json` preserves the ignored merged artifact hash,
exact cohort, fidelity, independently recomputable metrics, cost, and Q16
report/state hashes without publishing third-party report bodies. The complete
candidate remains at `artifacts/160/product-candidate.json`.

`scripts/check_f14_failed_candidate.py --self-test` verifies that this is a
complete but failed product experiment and rejects either hiding Q16 or claiming
that the artifact qualifies as product proof. Conditional F13 will change code
for this defect class and use targeted positive/negative evidence before any new
independent full candidate is preregistered.
