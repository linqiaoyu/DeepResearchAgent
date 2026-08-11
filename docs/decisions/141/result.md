# R141 — Reflection proposal contract

Status: COMPLETE for H17. Reflection remains `wired` until H18 closes the DecisionGate adoption loop.

Deterministic signals remain a separate typed artifact. The historical `llm_insight.insights` wire field is retained for trajectory compatibility, but every element is now a `ReflectionProposal` requiring a non-empty target, actionable recommendation, rationale, expected effect, and at least one typed evidence reference.

The reasoner envelope now declares `reasoner_kind` and `quality_bearing`. Synthetic fixtures are mechanically prohibited from claiming quality. `Reflector.reflect` continues to accept copied trajectory and decisions only; it has no `ResearchState` parameter and returns an additive artifact for the workflow to store.

The gate-wired checker reports two typed artifact families, proposal coverage 1.0, three rejected invalid proposal classes, one rejected synthetic quality claim, zero state parameters, and one stable artifact locator. A production locator mutation failed with the raw output retained under the ignored round evidence directory.

No paid provider was called; cost was CNY 0. No product-quality claim or default flip is made.
