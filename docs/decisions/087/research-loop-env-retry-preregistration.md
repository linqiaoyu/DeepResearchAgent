# 087 RESEARCH_LOOP environment-name retry pre-registration

Runnable source baseline: `30f71f79b2dad548adff04ae6b136ea160a3b45a`.

The prior retry used `RESEARCH_LOOP_MAX_ITERATIONS=2`; source inspection shows
that `Settings` reads `DEEPRESEARCH_RESEARCH_LOOP_MAX_ITERATIONS` instead.
Therefore both prior manifests still show `RESEARCH_LOOP_ENABLED=false` and
those packages (runs 20/45 and 21/45) are invalid and retained as such.

The final replacement pair uses the exact source baseline and all previously
fixed pair settings, with both arms setting
`DEEPRESEARCH_RESEARCH_LOOP_MAX_ITERATIONS=2`. Only
`RESEARCH_LOOP_ENABLED` changes from `false` to `true`; the registered
decision rule is unchanged. This is an execution-parameter correction, not a
post-hoc adjustment to the hypothesis or decision criterion.
