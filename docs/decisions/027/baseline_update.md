# 027 baseline update: task-specific capability selection default

## Motivation

`dynamic_capability_enabled` is now enabled by default. The fixed capability
set remains only the selector's explicit fallback; it is no longer the normal
policy for every question. The default LLM engine registers CNINFO disclosure
for applicable financial/event branches. Deterministic runs use a no-egress
fixture disclosure backend, so snapshot tests remain offline.

## Hunk attribution

| Snapshot file | Hunk | Added / removed lines | Category | Reason |
|---|---:|---:|---|---|
| `finance_structured.json` | report + manifest decisions | +250 / -4 | Expected capability change | The preserved report gains the reader-visible `AgentDecision` records and manifest gains selector decisions/flag. Existing evidence claims are unchanged. |
| `wealth_research.json` | report + manifest decisions | +250 / -4 | Expected capability change | Narrative branches explicitly select only `web_search`; the added material records that decision and its rejected alternatives. Existing evidence claims are unchanged. |

`git diff --numstat -- tests/golden_output` totals +500/-8, matching the two
rows above. No hunk is unclassified and no evidence or citation hunk changes
without an accompanying decision record.

## Decision and rollback

The baseline is updated because the new content makes actual tool selection
auditable in the default path. It is not updated merely to silence a test.
Rollback is a single default flip to `False`, removal of default CNINFO
registration, and restoration of the prior snapshot versions in a new,
reviewed commit.
