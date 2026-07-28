# ADR: opt-in LLM tool selection

## Decision

`LLM_TOOL_SELECTION_ENABLED` remains `false` by default and is classified as
`content_affecting`.  Deterministic capability rules remain the default
selector.  When explicitly enabled in LLM mode, the selector passes only
registered `CapabilityMetadata.tool_spec` schemas to the provider and rejects
unknown returned names.

Each returned tool call has one `AgentDecision` and one `selection_only`
trajectory tool trace.  The marker distinguishes a model selection from a
provider execution; strict replay validates its sequence while replay adapters
do not treat it as egress.

## Rationale

Tool choice can change the evidence set and ordering.  Default activation
would invalidate deterministic characterization output without sufficient
evidence of a quality gain.  The existing LLM ledger is reused so selection
cost, tokens, latency and cache behavior remain auditable.

## Promotion conditions

The default may change only after a preregistered evaluation shows an
improvement over deterministic selection on versioned cases, with no replay
regression, no budget-guard bypass, and a documented cost ceiling.  Until
then, an unknown capability is fail-closed and an exhausted `RunToolContext`
must reject the subsequent tool request and record the failure.
