# R106: auto structured-data routing tolerates a missing optional provider

## Context

CI run 31315375326 failed on `main` commit `fb8e1a5` in
`CompositeRoutingTests.test_live_mode_no_longer_pins_the_run_to_one_market`.
The test selects `DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=auto`, but CI installs
only `.[dev]`; constructing the optional AKShare provider then raised
`OptionalProviderDependencyError` because `akshare` is supplied by `.[finance]`.

## Decision

Treat a missing optional provider dependency as an unavailable route only for
the `auto`/`routed`/`composite` modes. The factory continues with the remaining
providers. Explicit `akshare` and `live` selections retain the existing
actionable dependency error.

## Guard

`test_live_mode_no_longer_pins_the_run_to_one_market` now forces AKShare's
import to fail and asserts that auto routing still returns the SEC provider.
Removing the `except OptionalProviderDependencyError` block produces the
original error; this counterexample was run in R106.
