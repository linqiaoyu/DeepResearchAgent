# Trajectory recording and replay

`TRAJECTORY_RECORD_ENABLED` is dark by default. When enabled, new sidecars use
schema v4 and record the run request, every LLM attempt, supported local or MCP
ToolSpec calls, node transitions including failures, AgentDecision/signal/memory
records, the manifest reference, artifacts, and a required typed `termination`
object. Terminal status is `completed`, `budget_exceeded`, or `failed`;
noncompleted outcomes require phase, error type, and error message. Legacy
schema-v3 files remain load/validation-compatible and must not contain the v4
termination object.

Strict replay is verified for completed schema-v4 trajectories. It consumes
recorded LLM and supported tool results, preserves the recorded run id, enforces
FIFO and exact prompts, and byte-compares report artifacts without provider
calls. Schema-v4 `budget_exceeded` and `failed` trajectories validate and
persist for audit, but replay returns a fail-closed non-replayable `cache_miss`.
Strategy-level replay remains unimplemented.

Coverage is no longer synthetic-only. Fixture tests cover the expanded
surfaces, a real-shaped LLM/disclosure integration test proves redaction-safe
offline replay, and Round 031 A4f recorded and reproduced a real-provider
Planner/Extractor/Reporter plus structured-data/disclosure run byte-for-byte.
Sidecars remain redacted on write; visualization, cross-run aggregation, and
production retention/access policy remain unimplemented.
