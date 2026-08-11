# R151: Reporter selection consumption

## Decision

Reporter now enforces its pre-writing Evidence decisions after normal drafting,
fidelity repair, and finance compaction but before reference pruning. Every
selected Evidence item must already be reader-reachable or is added in a
bounded, cited `选择证据补充` section before `参考来源`. A decision with no
Evidence emits an explicit insufficiency line. Invalid ownership or a missing
footnote fails closed.

This keeps one Reporter and the persisted `report_footnote_evidence` numbering
contract. The enforcement does not rebuild footnote numbers from Evidence
order; it uses the existing map and only restores the full reference catalog
when applying the new postprocessor to historical, already-pruned reports.

## Recorded regression

All 28 successful R149 states and reports were replayed offline; Q13 and Q21
remain absent and were not synthesized. The original reports contained one
orphaned sub-question, Q09 `sq2_caliber`. After selection consumption:

- successful recorded cases: 28/28
- selected Evidence covered: 145/145 (`1.0`)
- orphaned sub-questions: 0
- footnote misreferences: 0

The regression also exposed a reader-reach measurement defect. Provider-series
footnotes group records by the existing `footnote_key`, while reachability had
expanded only identical URLs. That falsely marked later AKShare periods behind
the same series footnote as unreachable. Reachability now expands the cited
representative by `footnote_key`, while footnote numbering still comes only
from the persisted state mapping.

## Boundary

This is offline/recorded evidence, not a live product score. No paid provider
call, full cohort, golden-truth edit, or Q13/Q21 splice was performed.

## Capability decision

`MCP_CLIENT_ENABLED` reached its registered R151 deadline. It is now permanent
opt-in, not pending and not finance-default. There is no registered hypothesis
that arbitrary external MCP servers improve the three finance product metrics;
default-on would instead add unconfigured process, trust, cost, and side-effect
boundaries. The R136 H2 proof remains its working opt-in proof. This decision
does not remove MCP from the Harness.
