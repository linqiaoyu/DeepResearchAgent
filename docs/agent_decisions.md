# Agent decisions

The current Agent makes bounded decisions in two established places. Planner
selects sub-questions, query text, source types, priorities, and whitelisted
structured-data requests. Critic decides whether evidence passes, which
explicit issue types apply, what targeted retry tasks are needed, and whether
the configured hard retry limit forces convergence.

`AgentDecision` is the common audit contract for new decision capabilities. It
records the decision type, actor, measured inputs, written criterion, outcome,
alternatives considered, loop iteration when applicable, and timestamp.
`record_agent_decision` writes the same object to the structured run trace;
the run manifest carries a decision summary; Reporter renders a reader-visible
decision section when records exist.

This task adds the recording infrastructure, not new research policies.
Research sufficiency loops, prior-period memory, deterministic arithmetic
checks, skill selection, and budget reallocation were not implemented. Their
future decisions must reuse `AgentDecision`, remain bounded, and be validated
before activation.

Humans still choose the research question, approve provider access and cost,
judge source licensing and materiality, approve forecasts and publication, and
make every investment or trading decision. The Agent does not have authority
to publish, trade, or spend without the explicit provider boundary.
