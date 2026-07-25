# 020-R decision record: reproduction stop

## Status

INCOMPLETE. The CI failure at `179f133` is confirmed by GitHub Actions run
`30174417402`, but it could not be reproduced locally with the exact job-level
environment or after isolating those environment variables.

## Evidence

- GitHub Actions recorded two failures in `tests/chaos/test_tool_failures.py`:
  the continuous-retry-budget scenario and the partial-subquestion report
  scenario.
- The specified local CI-environment command completed `Ran 382 tests` with
  `OK` twice.
- The eight chaos cases passed with all three relevant variables unset, with
  only `DEEPRESEARCH_MODE=deterministic`, and with only the two fixture-provider
  variables.

## Decision

Do not modify production code or chaos assertions without a reproducible
cause. This follows 020-R's R1 stop condition; therefore R2--R5, including
the gate-script change and any push, were not started.
