# 055 Guidance corrections

## Decision

Replace stale numeric and present-tense domain-coupling claims in `AGENTS.md`
with rules that are checked against Ruff `TID251` and
`scripts/check_domain_boundary.py`. Do not edit the generated Settings table.

Record the 048 audit correction in ADR 047: `pdfplumber` became a runtime
dependency in `e4dc665`; it is MIT licensed and presents no identified
compatibility issue. Update the architecture boundary text to describe the
manifest-visible empty-index RAG degradation. No README RAG wording existed to
correct.

## Verification

- `rg -n '5 增至 6|仍耦合在核心' AGENTS.md` returned no matches.
- `scripts/check_agent_guidance.py` passed.
- `scripts/sync_agents_settings.py --check` passed with all 25 flags.
- The complete local gate passed (713 tests, 4 skipped).
