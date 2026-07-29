# 044 · Evidence-first showcase redesign

## Decision

The public artifact remains a static, release-asset-backed showcase. Its visual
system now presents measurable research quality and reproducibility before any
product-like interaction. It deliberately does not expose a public prompt box
or imply a live research service.

## Delivered contract

- Home page contains a release verification panel, four source-derived quality
  metrics, a three-stage evidence chain, and an explicit no-live-provider
  boundary.
- Report discovery uses curated cards with topic, difficulty, type, and G3
  composite score.
- A project-owned Open Graph social card is generated and distributed with the
  static output.
- `test_showcase_contract_requires_boundary_and_visual_system` fails when the
  explicit no-live-provider boundary is removed. Its mutation output is kept in
  `_collab/044/showcase-contract-mutation.txt`.

## Evidence

`scripts/build_site.py` completed with 14 files and canonical release validation.
The targeted suite passed 5 tests. The complete gate passed 619 tests and all
configured checks. No live provider or external deployment was performed.
