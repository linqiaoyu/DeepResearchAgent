# 087 source-corrected acceptance amendment

Status: approved by the user on 2026-08-03 after the final completion audit.

This decision resolves three task-card constraints that conflict with immutable
repository evidence. It does not alter the final live reports, historical
packages, workflow graph, corpus, provider configuration, or A/B decisions.

## Historical reader-shape baseline

The task card quoted an 086 NIO reader baseline of at least 280 reader-visible
lines and 117 boilerplate lines. Its own metric definition counts non-empty
lines before `## 参考来源`; the immutable package measures 241 and 116.
The amended acceptance is the actual probe output retained in
`_collab/087/evidence/shape_086_baseline.log`: NIO
`241/116/4/2/2/0/0/4`, PDD `185/68/4/2/1/1/0/5`, with both probes red. The
final NIO and PDD packages must still satisfy the original green thresholds.

## Showcase source paragraph

The final NIO package contains the structured Company Facts revenue record but
not the verbatim 20-F revenue paragraph. The final run was registered against
the read-only 085 corpus. The showcase may therefore resolve that original
paragraph from the same registered corpus, provided that it records
`source_origin=registered_corpus`, has a resolvable chunk anchor, makes no
external request, and derives the displayed financial metric from the final
package evidence. `check_087_site_facts.py` enforces those properties.

## README architecture count

The architecture section may render its node count dynamically from
`workflow_contract_graph()` rather than an 087 live-run field. It must be
verified against the current graph on every README fact check; financial,
provider-cost, flag-state, and A/B values remain derived from their respective
recorded artifacts.

## Decision

With these source-corrected criteria, the three prior completion-audit
exceptions are accepted. The resulting claim remains strictly limited to the
finance SUT, its registered corpus, and the two final live topics; it does not
establish generic domain-pack support.
