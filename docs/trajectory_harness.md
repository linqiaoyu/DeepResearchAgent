# Trajectory recording and replay

`TRAJECTORY_RECORD_ENABLED` is dark by default. When enabled, one redacted
`trajectory.json` sidecar records the run request, every LLM boundary attempt,
every ToolSpec search call, node input/output summaries, AgentDecision records,
the run-manifest reference, and the exact report artifact.

Strict replay consumes recorded tool results instead of calling a search
provider, fails closed when a required call was not recorded, and requires the
reproduced report bytes to match. Strategy-level replay is not implemented; the
CLI and API reject that mode instead of relabeling strict matching.

The current tests use synthetic deterministic fixture trajectories only. No
real trajectory has been recorded. A later strategy-level replay design would
need its own audited matching contract; a policy that asks a new question still
needs a separately authorized provider call.

All sidecars pass through `security/content.py` redaction on write. The harness
does not provide a visualization, cross-run aggregation, or a real-client
recording in this task.
