# 087 Capability A/B restart pre-registration

Runnable source baseline: `20771020e293e50247043ce7059db80f4e603e33`.

The two earlier NUMERIC_CHECK packages consumed runs **1/45** and **2/45**
(workflow cost CNY 0.02362088 and CNY 0.02384856).  They are preserved as
negative evidence only: the post-run B3 shape probe found
`audit_sections_in_report=2`, so neither package satisfies the reader-report
acceptance criterion and neither will be used for promotion.  This is a new
experiment after the B3 correction, not a selection among repeated outcomes.

Before any restart run, the source baseline above contains the B1--B5 report
shape implementation and the fixed `check_087_capability_ab.py` decision
rule.  Each restart pair will use that exact commit, NIO's Chinese 2024 annual
report question, `--as-of 2026-07-01`, depth 1, read-only
`data/runtime/085-assets.db`, and
`finance_v1-43f11085-heading_page_first_1024_256`.  Only the listed flag may
differ, from `false` to `true`.

| Capability | Flag |
|---|---|
| NUMERIC_CHECK | `NUMERIC_CHECK_ENABLED` |
| RESEARCH_LOOP | `RESEARCH_LOOP_ENABLED` |
| CONTEXT_PACKER | `CONTEXT_PACKER_ENABLED` |
| TRAJECTORY_RECORD | `TRAJECTORY_RECORD_ENABLED` |
| SKILL_PACKS | `SKILL_PACKS_ENABLED` |
| SEMANTIC_JUDGE | `SEMANTIC_JUDGE_ENABLED` |
| PROGRESSIVE_DELIVERY | `PROGRESSIVE_DELIVERY_ENABLED` |
| DECISION_WEAVING | `DECISION_WEAVING_ENABLED` |

The decision rule is unchanged from the original pre-registration: enable a
capability only when at least one reader-shape measure improves, none worsens,
and both arms retain `verdict=PASS`, `footnote_misrefs=0`, and
`magnitude_mismatches=0`. Otherwise it remains off. The restart reserves 16
additional runs, leaving 27 of the round's 45-run limit after the two
preserved invalid packages; the CNY 30 total and CNY 15 single-run breakers
remain in force.
