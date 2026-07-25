# 020-R2 decision record: chaos run-context injection

## Status

COMPLETE pending CI confirmation.

## Findings

- Re-running GitHub Actions run `30174417402` at the same main SHA failed again
  with the same two chaos assertions. The result is deterministic in CI, not a
  green rerun by chance.
- `web_search` has `timeout_s=60.0`; the failing chaos fake calls return or
  raise immediately. CI reports both failures about two seconds after the
  unittest step begins, so the wall-clock-timeout explanation is not supported.
- `DeepResearchEngine.run()` creates a new `RunToolContext` and binds it to the
  adapter. The old chaos helper configured the adapter's pre-run context, so
  its requested retry budget and breaker threshold were discarded at run start.

## Decision

The chaos helper now injects the intended context through
`RunToolContext.for_run` for the duration of its run. This preserves every
assertion and makes each scenario's retry/breaker configuration explicit at the
same lifecycle boundary used in production. It does not change production
timeouts or production defaults.

## Local CI gate

`scripts/gate.py` is the sole local CI entry point. It checks its built-in
environment against `.github/workflows/ci.yml`, runs all CI checks with
`sys.executable`, and uses an ignored dedicated runtime database. The CI job
declares that runtime path too, so a stale developer database cannot alter demo
smoke behavior.
