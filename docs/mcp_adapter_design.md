# MCP adapter design

This is a design document, not an implemented MCP server. Implementation would require selecting and adding an MCP SDK, which is outside the zero-dependency scope of task 010.

## Contract mapping

| Core contract | Proposed MCP surface |
| --- | --- |
| `ToolSpec.name` | MCP tool name |
| `ToolSpec.version` | Tool annotation and server capability metadata |
| `input_schema` | MCP tool input JSON Schema |
| `output_schema` | Structured content schema; `ToolResult` remains the application envelope |
| `timeout_s` | Server-side deadline; client deadline may be shorter |
| `cost_class` | Tool annotation for policy/budget routing |
| `idempotent` | Idempotency annotation and retry eligibility |
| `has_side_effect` | Approval/policy annotation; side-effecting tools are never auto-retried |
| `ToolResult.error.kind` | Stable MCP error data code |
| degradation event | Successful transport response with `degraded=true` and explicit impact |

The server adapter should register existing `ToolSpec` instances and use `ReliableToolExecutor`; it must not duplicate retry policy in MCP handlers.

## Authentication and authorization

- Authenticate transport sessions with short-lived service credentials supplied by the deployment secret manager.
- Authorize per tool name, cost class, and side-effect flag.
- Never place provider keys in MCP arguments, tool descriptions, logs, or returned error text.
- Bind caller identity, run id, tool call id, and policy decision into structured audit logs.
- Require an idempotency key for side-effecting calls even when the initial tool set is read-only.

## Error semantics

| `ToolErrorKind` | MCP behavior |
| --- | --- |
| `transient`, `timeout` | Retryable application error; include retry-after hint when known |
| `rate_limited` | Resource/rate error with provider-safe retry-after |
| `auth` | Unauthenticated/permission error without credential details |
| `not_found` | Stable not-found error |
| `permanent` | Invalid request or non-retryable internal error |
| `budget_exceeded` | Resource-exhausted error; never retry inside the same run |

Transport failure and tool failure remain distinct. A successful MCP transport can carry a failed `ToolResult`; callers should not infer tool success from HTTP/session success.

## Process boundary

The proposed server owns serialization, authentication, deadline propagation, and tool registration. The research process owns run retry budget, circuit state, degradation events, and manifest aggregation. Correlation fields cross the boundary as metadata, not user-editable tool inputs.

## Why it is not implemented now

The repository has no MCP dependency, authentication subsystem, or production service identity. Adding a server now would violate the task's zero-new-dependency rule and create an unauthenticated demo endpoint. The typed contract is the deliberate seam for a later implementation after transport, identity, and deployment decisions are approved.
