# CLAUDE.md

@AGENTS.md

在分析、规划、修改代码或执行命令前，必须先读取并遵守仓库根目录的 `AGENTS.md`。
`AGENTS.md` 是完整的项目级规范和事实入口；本文件仅作为 Claude Code 的加载入口，
不独占项目规则。若两处文字出现冲突，以 `AGENTS.md` 为准。

## Claude Code

- `@AGENTS.md` 是 Claude Code 官方支持的导入语法，会在会话开始时展开。使用 `/memory`
  可确认已加载的指令文件；若该导入未加载，不得继续执行仓库任务，先解决配置问题。
