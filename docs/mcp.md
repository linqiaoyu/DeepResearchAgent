# MCP 双向集成

## 范围与协议

DeepResearchHarness 的 MCP 边界使用 UTF-8、行分隔的 stdio JSON-RPC 2.0，
目标协议版本为 `2025-06-18`。实现位于
`src/deepresearch_agent/mcp/server.py` 与
`src/deepresearch_agent/mcp/client.py`，没有引入 MCP SDK 或新的项目依赖。

生命周期按以下顺序执行：

1. 客户端发送 `initialize`，包含 `protocolVersion`、`capabilities` 和
   `clientInfo`；
2. 服务端返回协商后的协议版本、`capabilities` 与 `serverInfo`；
3. 客户端发送无 `id` 的 `notifications/initialized`，服务端不响应；
4. 客户端调用 `tools/list`，随后才能调用 `tools/call`。

服务端还对客户端探测的 `resources/list` 与 `prompts/list` 返回空列表；本轮没有实现
resources、prompts 或 Streamable HTTP。JSON-RPC 错误分别使用 `-32700` parse error、
`-32600` invalid request、`-32601` method not found 和 `-32602` invalid params，
响应 `id` 与请求对应。

## 服务端：把已有能力映射出去

服务端不维护第二套工具定义。`build_mcp_capability_registry()` 先把每个工具声明为现有
`CapabilityMetadata + ToolSpec`，`tools/list` 再机械映射 `input_schema`、
`output_schema`、幂等和副作用信息。

| MCP tool | 作用 | 约束 |
| --- | --- | --- |
| `research.start` | 发起一次研究 | 本轮只运行 deterministic + fixture；schema 含 `allow_paid`，LLM 模式即使确认也拒绝 |
| `research.evidence` | 取回一次 server-owned 研究的 Evidence | 只接受 `research_id` |
| `research.audit_export` | 导出引用闭合审计包 | 输出目录由服务端根据 `research_id` 决定，调用方不能传路径 |
| `research.snapshot_compare` | 比较两次 server-owned 研究快照 | 只接受两个 `research_id` |

MCP surface 不暴露任意文件读取、任意输出路径或命令执行。运行资产只写到启动者指定的
`--runtime-root`；这个参数属于本机进程配置，不是 MCP tool 参数。stdout 只承载
JSON-RPC，日志与可选的脱敏握手 trace 不混入协议输出。

启动示例：

```bash
PYTHONPATH=src .venv/bin/python -m deepresearch_agent.mcp.server \
  --runtime-root _collab/mcp-runtime
```

## 客户端：把外部能力注册回来

`MCPStdioClient` 使用 `subprocess.Popen(..., shell=False)` 启动一个明确命令，
以 JSON-RPC `id` 匹配响应，并用标准库 `selectors` 对每次响应设置超时。
`tools/list` 返回的工具被命名空间化为
`mcp.<server-name>.<remote-tool-name>`，随后注册进 015 的同一个
`CapabilityRegistry`；016 的 `DeterministicCapabilitySelector` 因而可以在运行时
发现这些候选能力。

发现与注册产生 `mcp_tool_discovery` `AgentDecision`，并通过
`MCP_DISCOVERY_NODE_CONTRACT` 与 `DecisionGate`。外部调用由
`ExternalMCPTool` 送入 010 的 `ReliableToolExecutor`，因此沿用：

- 每工具 timeout；
- 按 `ToolErrorKind` 的有界 retry；
- run-scoped retry budget；
- 显式 degradation；
- `ToolCallTrace(transport="mcp", server=...)`。

远端 `annotations` 默认不可信。未显式信任服务端时，发现工具按 `cost=high`、
`has_side_effect=true`、`idempotent=false` 注册；可能收费的工具还要求调用方显式
传入 `allow_paid=true`。只有调用者把一个精确配置的服务端标为 trusted，客户端才采纳
其 read-only、idempotent 与 `_meta` 成本/超时声明。

## 握手证据与诚实边界

本轮实际探测到 Codex CLI 0.139.0 与 Claude Code 2.1.172。Claude Code 通过本地
`claude mcp get` health check 启动本项目 server，并实际完成：

```text
initialize → notifications/initialized → tools/list
```

原始脱敏 stdio 记录保存在本轮运行资产
`_collab/018_mcp-skills/claude_handshake_raw.txt`。临时 local-scope 配置随后被移除。

第三方含 `tools/call` 的全序列握手是 **INCOMPLETE**。已安装 Claude CLI 没有暴露
零模型的直接 tool-call 命令；通过模型触发会违反 018 的零 API、零费用约束。独立标准库
验证脚本 `scripts/mcp_stdio_client.py` 完成并记录了：

```text
initialize → notifications/initialized → tools/list → tools/call
```

该完整序列的原始记录在 `_collab/018_mcp-skills/real_handshake.txt`，其中
`research.start` 返回 `real_api_cost_cny=0.0`。这份记录只证明自建客户端与服务端的
协议一致性，不表述为第三方完整握手。

## 为什么本轮用标准库

本轮目标不是声称标准库长期优于 SDK，而是在零新增依赖约束下直接证明实现理解了
JSON-RPC id、notification 无响应、生命周期排序、协议/工具错误分层、stdio stdout
纯净性与超时边界。生产化若需要 Streamable HTTP、认证、会话恢复或更快跟随协议演进，
应重新评估官方 SDK；当前实现不提供这些能力。

## 零成本验证

```bash
PYTHONPATH=src:. .venv/bin/python -m unittest \
  tests.unit.test_mcp_server \
  tests.unit.test_mcp_stdio_client \
  tests.unit.test_mcp_client -v
```

测试使用自身 server 作为外部进程，覆盖 4 个工具、四类 JSON-RPC 错误、付费拒绝、
不可信注解、timeout/retry/degrade、动态注册、AgentDecision 和 MCP 轨迹。它不连接
第三方远端 server，也不证明真实工具提高研究质量。
