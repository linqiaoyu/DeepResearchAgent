# R169 — CI characterization snapshot synchronization

## Decision

**PASS.** The deterministic CI failure was caused by four characterization snapshots
retaining the pre-R168 hashes for the four prompts changed by the project-name
harmonization. The snapshots now record the hashes of the current prompt sources.

Only the `prompt_hashes` fields in the four affected snapshots changed. No gate,
test assertion, prompt source, registry entry, evaluation set, or fixture content was
weakened or rewritten.

## Verification

- The remote `Deterministic MVP` job failed after running 1,232 tests with exactly
  four snapshot failures; both service jobs passed. The final
  `no_silent_skips=FAIL` line was the suite-level summary, not the root cause.
- `git diff --check`: PASS.
- `scripts/check_prompt_drift.py`: PASS; 7 prompts.
- `scripts/check_guard_wiring.py --self-test`: PASS; 63/63 guards wired.
- Independent SHA-256 verification: PASS; 4 prompt sources match all 4 snapshots.
- JSON parsing: PASS for all 4 changed snapshots.
- Full local gate: INCOMPLETE. The existing macOS `.venv` contains dataless package
  files; the gate passed its initial guard/capability/Harness checks but could not
  complete dependency-backed tests. This is an environment limitation, not a
  product assertion result.

## Scope

The task branch is `task/169-ci-fix`. No remote write, commit, push, merge, or PR
operation was performed.
