# 087 Capability A/B source-fix restart pre-registration

Runnable source baseline: `30f71f79b2dad548adff04ae6b136ea160a3b45a`.

The first restart NUMERIC_CHECK off arm consumed run **3/45**.  Its reader
shape probe printed green, but direct inspection revealed four
`outdated_source` entries for annual Company Facts and one 20-F legal-template
projection.  The probe had not recognized the Company Facts source title.
That package is retained as a failed probe and is excluded from promotion.

Before the next run, this commit fixes both source-level classifications and
extends the shape probe.  The comparison protocol, topic, date, depth, corpus,
index version, flag list, and promotion rule remain exactly those in
`capability-ab-restart-preregistration.md`; only the repaired source baseline
changes.  The replacement NUMERIC_CHECK pair and all remaining pairs will run
on this exact commit with one `*_ENABLED` flag changed false→true.

Runs 1--3 are counted against the 45-run / CNY 30 authorization and are never
eligible to be selected as favorable results.  This restart plans 16 valid
runs, leaving 26 of 45 available before final validation.
