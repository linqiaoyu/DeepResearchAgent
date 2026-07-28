# B8 real-provider run — INCOMPLETE

On 2026-07-28 the repository owner authorized up to three bounded live attempts.
All three credentials were present; a minimal `openai/qwen3.7-plus` judge call
succeeded. Total estimated LLM cost, including the probe, was 0.10164388 CNY.

Attempt 1 used real LLM, Tavily, and CNINFO, but AKShare `symbol_resolve` failed
within its existing bounded retry policy and recorded a degradation event. Attempt
2 stopped at the reporter's mechanical Evidence fidelity contract. Attempt 3
completed with real LLM/judge/CNINFO, but its trajectory did not actually invoke
AKShare despite the request asking for the comparison.

The required three-layer evidence is therefore absent. This decision records B8
as INCOMPLETE; it does not infer numerical correctness from a completed pipeline.
The DASHSCOPE credential should be rotated because it was exposed in conversation;
no credential characters are retained here.

The first attempt also exposed a local retry defect: after a timeout, the
AKShare adapter queued retries behind the same occupied single-worker executor.
The adapter now gives each bounded attempt an independent worker and reports the
timeout duration. A unit test proves a timed-out first call does not prevent the
second attempt from succeeding. This is a new experiment boundary; the authorized
three live attempts were already exhausted, so no fourth live call was made.

Run manifests now record separate configured fidelity and actual provider usage.
An unused configured provider is recorded as `unused`, and the corresponding
`actual_realness` is `mixed`; this prevents a configured AKShare adapter from
being mistaken for an executed AKShare call. The deterministic characterization
snapshots changed only by these new operational manifest fields.

## B8 continuation — four-layer verification

The continuation kept the original three failed attempts above as failed evidence;
it did not reinterpret them as successful runs. Four additional bounded live attempts
were authorized after a zero-cost diagnosis and repair sequence.

The zero-cost AKShare probe observed `akshare==1.18.64`. A known six-digit symbol
no longer needs the separate full-market symbol resolution call. The observed source
field for this metric was `营业总收入`, which is the established alias of the requested
canonical metric `营业收入`; the filtered provider call returned one record,
`362012554000.0` yuan. Compared with the recorded fixture value `362012600000.0`
yuan, the relative difference is `1.270674004164495931909552319E-7`.

The continuation also makes an executed zero-record structured request observable:
it records an explicit degradation, counts no real structured-data usage, and persists
all five structured-data counters in the manifest. This turns attempt-3's previously
unobservable ambiguity into a measurable condition. The deterministic D4 run produced
one real AKShare record, so its result establishes that attempt-3's failure was not a
missing deterministic request: the repaired path can execute and return a record.
Its other layers remain fixtures, therefore D4 is correctly `mixed`, not a real E2E run.

Live attempts 4–6 completed but remained `mixed`: primary disclosure satisfied the
financial branch and suppressed the selected independent web-search query, leaving
`provider_usage.search=0`. The minimal repair retains the first explicitly selected
independent search while still avoiding its redundant fetch when primary disclosure has
already hydrated the result. Attempt 7 then completed with
`provider_usage={llm:1, search:1, disclosure:1, structured_data:1}`, all four actual
provider fidelities `real`, one structured-data record, and `actual_realness=real`.
The sanitized manifest is `b8-real-run-manifest.json`.

For the final run, the CNINFO annual-report value was `362,012,554` thousand yuan and
the AKShare value was `362,012,554,000` yuan: they are exactly equal after the stated
unit conversion. The mechanical grounded-fact renderer still recorded one explicit
fidelity degradation for the revenue label; it no longer aborts the complete run, and
the manifest and source evidence remain available for review.

Costs for attempts 4–7 were respectively 0.04261108, 0.04263900, 0.04632644, and
0.04676320 CNY. Together with the previously recorded 0.10164388 CNY, cumulative
043 B8 cost is 0.27998360 CNY, below both applicable caps; no cost or wall-clock
circuit breaker fired. The DASHSCOPE credential rotation recommendation remains in
effect; no credential characters are recorded here.

This four-layer run closes B8's execution criterion. It does **not** establish the B5
product-improvement hypothesis relative to 031: this continuation has no controlled
before/after numerical-accuracy comparison against 031. That product hypothesis is
therefore not claimed as improved merely because the pipeline completed.
