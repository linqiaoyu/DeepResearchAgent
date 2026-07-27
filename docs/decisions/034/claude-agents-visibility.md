# 034 CLAUDE.md 与 AGENTS.md 的共享规则入口

## 决定

`AGENTS.md` 是本仓库所有编码 Agent 的完整、可单独使用的项目规则入口。环境、安装、
自检、完整本地 gate、目录/运行产物边界和已知执行陷阱均归入该文件；Settings 默认值表
仍由 `scripts/sync_agents_settings.py` 生成。

`CLAUDE.md` 使用 Claude Code 官方的 `@AGENTS.md` 导入语法，并只保留 Claude Code
加载/确认建议。这样 Claude Code 在会话开始时展开共享规则，而支持 `AGENTS.md` 的其他
Agent 不依赖 Claude Code 的加载行为。

## 依据

- Claude Code 官方文档说明它读取 `CLAUDE.md` 而非 `AGENTS.md`，并推荐在已有
  `AGENTS.md` 的仓库中用 `@AGENTS.md` 导入。
- 原 `CLAUDE.md` 独占了会影响所有 Agent 正确执行的环境、gate 和目录事实，且包含
  易漂移的数量统计和已被源码否定的回放环境变量副作用。
- `scripts/gate.py` 原先未运行 CI 的 Settings 文档检查，也未传入 CI 使用的 v2 eval
  baseline；现已对齐，并增加轻量指令文件检查。

## 防漂移

`scripts/check_agent_guidance.py` 检查导入、AGENTS 覆盖、CLAUDE 不重复共享命令和生成
Settings 标记。它在 CI 和本地 gate 中执行；对应单元测试删除 `@AGENTS.md` 后确认检查
会失败。
