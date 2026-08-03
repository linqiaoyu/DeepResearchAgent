# 087 RESEARCH_LOOP retry pre-registration

Runnable source baseline: `30f71f79b2dad548adff04ae6b136ea160a3b45a`.

The first RESEARCH_LOOP pair is invalid for promotion: both manifests record
`RESEARCH_LOOP_ENABLED=false`, because the source represents this flag as
`research_loop_active` and the shared default `research_loop_max_iterations=1`
prevents activation. The two packages remain retained evidence and count as
runs 6/45 and 7/45; neither is eligible for selection.

Before the replacement pair, both arms will set the same non-flag operating
parameter `RESEARCH_LOOP_MAX_ITERATIONS=2`, required for the registered flag
to become active. The only differing capability flag remains
`RESEARCH_LOOP_ENABLED=false` versus `true`; topic, as-of date, depth, corpus,
index, source commit, budget, and all other flags remain unchanged. The
unchanged pre-registered decision rule applies.
