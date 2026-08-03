# 087 measured result

The registered A/B checker evaluated eight paired live comparisons: four were
promoted and four were kept off. Each valid arm retained `verdict=PASS`,
`footnote_misrefs=0`, and `magnitude_mismatches=0`.

| Capability | Reader-visible lines, off → on | Decision |
|---|---:|---|
| NUMERIC_CHECK | 15 → 13 | promoted |
| RESEARCH_LOOP | 13 → 13 | kept_off |
| CONTEXT_PACKER | 18 → 15 | promoted |
| TRAJECTORY_RECORD | 15 → 15 | kept_off |
| SKILL_PACKS | 15 → 15 | kept_off |
| SEMANTIC_JUDGE | 18 → 16 | promoted |
| PROGRESSIVE_DELIVERY | 15 → 15 | kept_off |
| DECISION_WEAVING | 18 → 13 | promoted |

Final registered validation used runs 24/45 and 25/45. NIO measured 13
reader-visible lines, 0 boilerplate lines, 2/2 answered metrics, one derived
metric, and workflow cost CNY 0.08938328 plus RAG cost CNY 0.0366520. PDD
measured 11 reader-visible lines, 0 boilerplate lines, 1/2 answered metrics
plus one explained gap, and workflow cost CNY 0.09856776. Both used
`SecCompanyFactsProvider`, passed structured-manifest validation and citation
closure, and did not use an additional contingency run.

This evidence validates only the finance SUT with the frozen 60-document SEC
20-F corpus, two depth-1 topics, and one Chinese plus one English report. It
does not establish a generic domain-pack implementation.

The final audit's source-corrected acceptance decision is recorded in
`docs/decisions/087/acceptance-amendment.md`. It preserves the immutable 086
packages and final live artifacts while making the historical-baseline,
showcase-source, and generated-architecture evidence rules explicit.
