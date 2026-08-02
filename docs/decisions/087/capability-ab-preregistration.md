# 087 capability A/B preregistration

Pre-registration commit: `928c332`.

Each pair uses the NIO Chinese topic, `--as-of 2026-07-01`, depth 1, the
read-only `data/runtime/085-assets.db` corpus, and index version
`finance_v1-43f11085-heading_page_first_1024_256`.  The two arms are run on
this same commit with exactly one environment flag changed.

| Capability | Off arm | On arm |
|---|---|---|
| NUMERIC_CHECK | `NUMERIC_CHECK_ENABLED=false` | `NUMERIC_CHECK_ENABLED=true` |
| RESEARCH_LOOP | `RESEARCH_LOOP_ENABLED=false` | `RESEARCH_LOOP_ENABLED=true` |
| CONTEXT_PACKER | `CONTEXT_PACKER_ENABLED=false` | `CONTEXT_PACKER_ENABLED=true` |
| TRAJECTORY_RECORD | `TRAJECTORY_RECORD_ENABLED=false` | `TRAJECTORY_RECORD_ENABLED=true` |
| SKILL_PACKS | `SKILL_PACKS_ENABLED=false` | `SKILL_PACKS_ENABLED=true` |
| SEMANTIC_JUDGE | `SEMANTIC_JUDGE_ENABLED=false` | `SEMANTIC_JUDGE_ENABLED=true` |
| PROGRESSIVE_DELIVERY | `PROGRESSIVE_DELIVERY_ENABLED=false` | `PROGRESSIVE_DELIVERY_ENABLED=true` |
| DECISION_WEAVING | `DECISION_WEAVING_ENABLED=false` | `DECISION_WEAVING_ENABLED=true` |

For every arm, record the eight `check_087_report_shape.py` measures, the
existing fidelity and retrieval checks, manifest validation, elapsed time, and
both workflow and RAG cost.  An enabled arm is **promoted** only if at least
one shape measure improves, none worsens, and `verdict=PASS`,
`footnote_misrefs=0`, and `magnitude_mismatches=0` are unchanged. Otherwise
it is **kept_off**. This rule is fixed before the first paired run.

The A/B budget is 16 runs, within the round limit of 45 runs and CNY 30;
single-run cost remains subject to the existing CNY 15 circuit breaker.
