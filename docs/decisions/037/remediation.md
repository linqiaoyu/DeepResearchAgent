# 037 remediation decisions

## Scope

This round remediates the concrete N1–N11 findings in the 037 review. N12 was
an architectural priority note rather than a defect, so no unrelated API
bootstrap refactor was included.

## Decisions

- Provider provenance is declared explicitly as `real`, `fixture`, or
  `replay`; missing or invalid declarations produce fail-closed `unknown`.
  Mixed layers are reported as `mixed`. Class-name inference is removed.
- Both structured and extracted numeric mirrors use `Decimal`; no float mirror
  remains on the numeric-guard path.
- CNY cost is nullable when no billing ledger exists. `null` means unknown,
  never zero spend. Deterministic snapshots and audit bundles were updated as
  characterization artifacts for this contract change.
- Metric coverage adds `partially_cited`, with observed and missing periods.
  This preserves valid one-period evidence without claiming an absent period.
- Unit parsing accepts `千元` / `百万元` / `亿` on the main extraction path and
  uses a non-negative local-text boundary.
- Disclosure lookup uses a typed request symbol or an explicitly labelled /
  parenthesized code; a bare six-digit number is not treated as a stock code.
- Public LLM demo execution reserves the per-run ceiling before provider work.
  A failure settles the reservation conservatively, preventing an unrecorded
  paid path.
- The repository now declares and ships the owner-selected MIT License.

## Validation

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py` passed with 558
tests, deterministic demo/eval smoke, and baseline comparison pass.
