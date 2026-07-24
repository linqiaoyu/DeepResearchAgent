# 研究记忆层

## 统一协议、作用域与生命周期

`MemoryStore[WriteT, QueryT, ResultT]` 是记忆实现的前向协议，只规定 `write`、
`query`、`scope` 和 `lifecycle`。`MemoryScope` 明确 namespace、domain 和可选
research_id，防止不同研究或领域静默串用数据。生命周期分为单次运行 `run`、
跨运行 `cross_run` 和持久 `persistent`。

本轮实现情景记忆、语义记忆，并把已有 context packer 适配为工作记忆；不实现程序性
记忆。016 的程序性记忆必须实现同一协议，并声明自己的作用域、生命周期、写入对象与
查询结果，不能绕开记忆边界直接读取其他运行的 state。

## 情景记忆 EpisodicMemory

情景记忆以 `(question_id, as_of)` 为主键。每条 `EpisodicRecord` 直接持有 012 已有
`ResearchSnapshot` 和可选的 014 `trajectory.json` 引用；没有复制或另造 snapshot、
trajectory 的序列化格式。查询可指定完整主键，也可取同一 question 的全部期次，结果
按 as_of、manifest_ref、trajectory_ref 稳定排序。同一主键再次写入是显式替换。

## 语义记忆 SemanticMemory

语义记忆保存已抽取、归一的事实，不替代保存逐字摘录的 Evidence Store。索引固定为
四键：

`(entity, normalized_metric, period, scope)`

查询可以给出任意键子集，并返回每个完整四键的历次取值、单位、来源 URL、as_of 和
置信度。观察值按 as_of、值、来源、置信度稳定排序。`scope` 是索引的一部分，因此
“2024Q3 单季归母净利润”和“2024 前三季累计归母净利润”永远是两条时间序列，不会因
文本相似而合并。

## 为什么现在不引入向量检索

金融数值 claim 的正确检索原语是四键精确匹配，不是语义相似。语义相似很可能认为
“归母净利润 2024Q3 单季”和“净利润 2024 前三季累计”高度相似，但口径混合正是本项目
19 处金标准缺陷的病因。当前结构化 retriever 因此是默认实现，接口仍可插拔。

只有当主要检索目标从结构化指标转向无法可靠归一为四键的非结构化叙事，例如管理层
语气、竞争战略主题或监管论述，并且精确/字段检索的召回缺口已由真实样本证明时，才
触发向量适配器设计。届时向量结果仍不能绕过 scope、来源和 as_of 校验。

## 工作记忆 ContextWorkingMemory

`ContextWorkingMemory` 是现有 deterministic context packer 的 run-scoped 适配器。
Reporter 在 `CONTEXT_PACKER_ENABLED=true` 时先 `write` 当前 Evidence，再用 topic、
budget、as_of `query` 打包结果。开关继续默认关闭；关闭时不会写入或查询工作记忆，
现有 Evidence、报告和双题面 characterization 保持逐字一致。

## 明确不做什么

本轮不实现程序性记忆，不引入向量库、embedding 或外部 API，不修改 Evidence Store
数据库合同，也不做自动遗忘、摘要或压缩。情景与语义实现当前为确定性内存索引；
持久化适配器属于后续实现，不能把这里的生命周期声明误读为已经部署跨进程数据库。

## 跨期研究行为

`PRIOR_MEMORY_ENABLED` 默认关闭并归类为 `content_affecting`。启用后，Engine 按当前
topic 的稳定 question_id 查询 `EpisodicMemory`，只选择 as_of 早于本期的最近一条
`ResearchSnapshot`；本轮不跨越两期。

Planner 把每个子问题分类并记录 `prior_memory_classification` 决策：

- `verify`：子问题命中置信度不低于阈值且非 uncertain 的上期 claim，需要核实是否仍
  成立；决策写明 claim、confidence、as_of 与来源 URL。
- `watch`：命中的上期 claim 低置信度或 uncertain，本期重点关注。
- `explore`：没有命中上期 claim，应寻找上期未覆盖的信息。

verify 的旧 URL 是优先复核目标，不是唯一检索范围。Researcher 即使获得旧 URL，也
必须为独立查询保留至少一次调用；有分支上限时先预留这一次调用，再安排旧 URL fetch。
这是防止确认偏误的硬约束，代码注释和测试均覆盖。

Critic 在相同 `(entity, normalized_metric, period, scope)` 下比较上期与本期数值。
数值实质矛盾且当前 Evidence 没有同比、环比、原因或变化说明时，产生
`contradicts_prior` high issue，并进入既有 retry queue。相同值、不同 scope，或有
证据解释的变化都不会触发。

Reporter 的“与上期结论的差异”来自 Agent 本轮主动核实的上下文，列出
verified_unchanged、changed 或 not_verified 及本期 Evidence。它不同于
`scripts/diff_snapshots.py`：后者是两份已完成快照的离线机械比对；前者知道 Planner
为何把问题标成 verify/watch/explore、研究中找到了什么，以及变化是否有证据支撑。
