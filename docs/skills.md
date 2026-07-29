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

## 与 DomainPack 的边界

018 的资源迁移本身只抽出了一个边界清晰的规则表；此后领域迁移已继续推进。当前
`domains/finance` 通过显式 `DomainPack` 承接规划、披露查询和标题规则、结构化数据别名、
指标覆盖、表格抽取、报告渲染、skill 适用性与数值检查/引用策略。核心源码对
`domains.finance` 的直接 import 为 0，领域边界守卫把剩余金融字面量限制在 3 个文件、
9 行，保留原因见 `docs/decisions/043/domain-boundary-residual.md`。

Skill pack 与 DomainPack 仍是两个不同概念：前者是默认关闭、metadata-first 的可选运行时
资源与能力包；后者是由 composition root 选择并注入的领域策略合同。当前只有 finance
是真实注册领域，`NullDomainPack` 仅用于边界测试，因此不能宣称已经完成通用领域产品化。
新增领域必须实现同一显式协议、在 registry 注册，并完成 provider/eval 资产声明、默认
characterization 与完整 gate。

## 扩展一个 pack

1. 新建与 frontmatter `name` 同名的目录和 `SKILL.md`；
2. 把可延迟读取的材料放入单层 `resources/`；
3. 在 `capability.json` 声明与 `ToolSpec` 一致的 name、成本、副作用、schema 和主资源；
4. 增加确定性适用策略，证明 false 路径没有 resource read；
5. 验证能力注册、`AgentDecision`、`DecisionGate`、manifest 分类与严格回放；
6. 若迁移既有规则，保存迁移前后 SHA-256 与默认 characterization 证据。

当前 loader 不支持热重载、远程下载、嵌套资源目录、自动信任或自动创建新 domain。
这些限制避免 skill 变成绕过 ToolSpec、预算和 manifest 的第二执行面。
