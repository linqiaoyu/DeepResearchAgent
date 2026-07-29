# 045：当前文档与 README 事实同步

本轮仅修改受管 Markdown 文档与 README，没有改动源码、配置、测试、prompt、数据或
fixture。历史决策记录保留当时事实；当前说明文档以 044 后的源码、`Settings`、
`pyproject.toml`、CI 和既有决策记录为准。

## 已修复的漂移

- 将 `DYNAMIC_CAPABILITY_ENABLED=true`、`BRANCH_BUDGET_ENABLED=true`、
  `TOOL_CONTRACT_ENABLED=true` 与 `STRUCTURED_OUTPUT_ENABLED=true` 同步到架构、
  编排、决策、方法边界、生产就绪度和 README。
- 将领域说明从 018 的“规则表迁移首付”更新为当前显式 `DomainPack` 依赖倒置：
  核心 concrete-finance import 为 0，金融字面量受 3 文件/9 行 allowlist 棘轮约束；
  finance 仍是唯一真实注册领域，未宣称通用领域产品化。
- 将 search provider 缺 key 行为修正为 fail-fast，移除静默 fixture 回退说明；
  同步 LLM tool selection、run-scoped 预算、四层真实 provider 执行与 Reflector/
  procedural-memory 的最新证明边界。
- 将 Python、安装、baseline 和本地验证命令统一到 Python 3.12 与
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py`。
- README 最后更新，保留静态站、MCP、Skill、Docker 和人工责任的诚实边界。

## 可执行验收

- `scripts/check_domain_boundary.py`：
  `import_sites=0 literal_files=3 literal_hits=9 lexicon_terms=33`。
- Settings 文档同步：22 个布尔开关一致。
- 本地 Markdown 链接：检查 89 个，缺失 0 个。
- 完整 gate：617 项 unittest 通过；demo `phase=done status=done`；
  5-case eval baseline comparison `status: pass`；受跟踪文件未被 gate 改写。
- 公开静态站在 2026-07-29 返回 HTTP 200；本机 Docker 与 Podman 均不可用，
  因此未新增镜像构建声明。

本轮没有真实 provider 或付费 LLM 调用，没有 push、merge 或其他远端写。
