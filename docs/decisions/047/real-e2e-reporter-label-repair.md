# Real E2E reporter-label repair

## Decision

Keep the one preregistered real end-to-end attempt as a failed experiment and
repair the deterministic reporter defect with the smallest domain-local change.
Do not claim a completed three-provider E2E from this attempt, and do not rerun
it without a new authorization because the repaired code makes the prior result
non-comparable.

## Observed result

The attempt used the configured live workflow and retrieval path. It recorded
six retrieval-ledger rows (embedding and rerank) with ¥0.148113 RAG cost. The
planner recorded 2,547 tokens and ¥0.00327492. Research reached Reporter after
31 sources and seven Evidence records, then terminated with `ValueError:
grounded fact renderer returned a partial or ambiguous batch` before a final
report or RunManifest was serialized.

The run is therefore evidence of live provider reachability only; it is not a
successful real E2E, nor proof of final delivery, retrieval quality, or
three-provider completion.

## Root cause and repair

Multiple subquestions requested the same financial metric. The finance renderer
used that metric string as every reader-claim label and as every required batch
label, while Reporter correctly rejects a batch whose labels are ambiguous.

`FinanceGroundedFactRenderer` now keeps the metric label unchanged when it is
unique, and otherwise prefixes it with the stable subquestion identifier. The
renderer consequently supplies a one-to-one required-label, claim-or-gap batch
without weakening Reporter's partial/ambiguous-batch guard. A unit regression
test creates two requests for the same metric and asserts that their labels are
distinct.

## Budget correction

The package runner assigns the RAG adapter ¥12 when the workflow LLM retains
its ¥3 hard limit. This preserves the registered single-run ¥15 ceiling instead
of treating both limits as independent allowances.

## Verification

`tests.unit.test_reader_fidelity` passed (12 tests), and Ruff passed for the
changed renderer and test. The full local gate is required after this source
change and is recorded separately.
