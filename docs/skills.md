# Skill packs

## 机制

Skill pack 是运行时上下文与能力包，不是完整 domain pack。每个目录包含：

```text
<skill-name>/
├── SKILL.md
└── resources/
    ├── capability.json
    └── <prompt fragment / rule table / template>
```

`SKILL.md` frontmatter 只含 `name` 与 `description`。`SkillPackLoader.discover()`
只读取这两个 metadata 字段；适用策略返回 true 后，loader 才枚举
`resources/`、校验 `capability.json` 并读取资源。未适用路径的测试断言
`resource_reads == 0`。

适用选择产生 `skill_selection` `AgentDecision`；真正读取资源和注册能力产生
`skill_load` `AgentDecision`。两者分别声明
`SKILL_SELECTION_NODE_CONTRACT` 与 `SKILL_LOAD_NODE_CONTRACT`，并通过
`DecisionGate`。skill 能力继续注册到 015 的 `CapabilityRegistry`，没有平行 registry。

`SKILL_PACKS_ENABLED=false` 是默认值。关闭时 engine 不做 metadata discovery、
不记录 skill 决策，也不把 flag 放进默认 manifest payload；开启时该 flag 按
`content_affecting` 阻断跨代可比性。

## 首个 pack：金融数值口径

首个 pack 位于
`skills/finance-metric-normalization/`。研究题面包含营收、利润、毛利率、资本开支等
金融数值词时加载；不涉及金融数值时不加载资源。

迁移对象原为 `data/finance_metric_normalization.json`，现在唯一资源路径为：

```text
skills/finance-metric-normalization/resources/finance_metric_normalization.json
```

迁移前后的文件均为 1299 字节，SHA-256 均为：

```text
8e69cf6ce69201f803ae9cafcad5b74bab841be5b313f6edbcdc2f7d0e153baf
```

Git 将该变更识别为 100% rename；`cmp` 和双 SHA-256 证据位于本轮运行资产
`_collab/018_mcp-skills/stage5_sha256.txt`。默认关闭时，Critic 与结构化输出直接读取
迁移后的相同字节事实源，因此两题面 characterization 逐字不变；开启且适用时，
loader 额外注册 `skill.finance.metric_normalization`，规则内容没有变化。

## 这是 010 领域债务的首付

该迁移只抽出了一个边界清晰的规则表，不代表领域解耦完成。以下金融行为仍硬编码：

- `agents/planner.py`：结构化金融 capability 与合规/风险查询模板；
- `agents/researcher.py`：`financial_indicators` 等结构化请求分派；
- `agents/critic.py`：numeric conflict、旧来源、反方和 retry 判据；
- `structured_output.py`：中文金融 metric 的正则与金融化表格语义；
- `tools/akshare_structured_data.py` 与
  `tools/fixture_structured_data.py`：金融字段、默认指标和部分 alias；
- `agents/reporter.py`：投资建议免责声明与金融报告呈现；
- Golden audit 与金融 fixture：仍属于现有评测/数据边界。

因此仓库仍没有 `domains/finance` 或 `domains/competitive`。目标 domain pack 的
`tools/`、`prompts/`、`templates/`、`eval/` 与 `domain.yaml` 约定保持不变；新增领域
前仍需完成 finance 等价抽取、旧路径兼容、资源哈希和默认 E2E 证明。

## 扩展一个 pack

1. 新建与 frontmatter `name` 同名的目录和 `SKILL.md`；
2. 把可延迟读取的材料放入单层 `resources/`；
3. 在 `capability.json` 声明与 `ToolSpec` 一致的 name、成本、副作用、schema 和主资源；
4. 增加确定性适用策略，证明 false 路径没有 resource read；
5. 验证能力注册、`AgentDecision`、`DecisionGate`、manifest 分类与严格回放；
6. 若迁移既有规则，保存迁移前后 SHA-256 与默认 characterization 证据。

当前 loader 不支持热重载、远程下载、嵌套资源目录、自动信任或自动创建新 domain。
这些限制避免 skill 变成绕过 ToolSpec、预算和 manifest 的第二执行面。
