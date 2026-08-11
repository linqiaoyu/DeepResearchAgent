# R135 — MCP stdio interoperability

## Verdict

PASS. H11 is complete. `mcp` remains `wired` until H12 proves untrusted-server
safety and Engine fallback composition; no premature H2 promotion is made.

## Interoperability evidence

Three separate subprocesses completed initialize, initialized notification,
tools/list, tools/call, and transport close through the production
`MCPStdioClient`. One used this project's MCP server. Two used a zero-dependency
JSON-RPC/MCP fixture that does not import or reuse the project server.

All three discovered capabilities were converted to bounded `ToolSpec`s, spent
one request from their run-scoped fetch budget, and emitted exactly one
`transport=mcp` trajectory tool call. All three subprocesses exited after stdin
close; residual processes and captured `ResourceWarning`s were zero.

The first combined MCP suite exposed a defect that ordinary assertions had
hidden: a server failing during discovery was never closed, and `Engine.close`
did not own successfully registered MCP clients. The suite printed one live
subprocess warning and three unclosed-pipe warnings while still reporting
`OK`. The engine now closes a partially constructed client on discovery failure
and closes all owned MCP clients during normal shutdown. A deliberately
bad-protocol independent server now degrades explicitly with zero residual
processes; the targeted suite passes with `ResourceWarning` promoted to error.

The project-server call used its deterministic fixture mode. Independent server
calls echoed recorded values. No external network or provider was involved and
no MCP mechanism or finance-quality benefit is inferred beyond stdio protocol
interoperability.

## Falsification

The production `ExternalMCPTool` trajectory transport was temporarily changed
from `mcp` to `local`. The gate-wired probe exited 1 with
`mcp_interop_self_test=FAIL production probe is dirty`. Restoring the production
line returned all ten metrics to contract. Eight output mutations additionally
reject missing process success, self-only testing, missing ToolSpec/budget/trace
coverage, normal or abnormal residual processes, and a resource warning.
