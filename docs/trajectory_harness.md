# Trajectory recording and replay

`TRAJECTORY_RECORD_ENABLED` is dark by default. When enabled, one redacted
`trajectory.json` sidecar records the run request, every LLM boundary attempt,
every ToolSpec search call, node input/output summaries, AgentDecision records,
the run-manifest reference, and the exact report artifact.

Strict replay consumes recorded tool results instead of calling a search
provider and requires the reproduced report bytes to match. Strategy replay
uses the same cache while allowing the caller to predeclare calls required by a
changed policy. If a required call was not recorded, replay stops with
`cache_miss`; it never invents a response or silently falls back to a provider.

The current tests use synthetic deterministic fixture trajectories only. No
real trajectory has been recorded. Once a real run is recorded in the next
validation task, policy changes that stay within its call set can be exercised
offline; a policy that asks a new question still needs a separately authorized
provider call.

All sidecars pass through `security/content.py` redaction on write. The harness
does not provide a visualization, cross-run aggregation, or a real-client
recording in this task.
