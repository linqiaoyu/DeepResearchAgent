# 043：领域边界棘轮

043 首先把 concrete finance import 与金融字面量的基线测量变成受版本控制的离线守卫。
初始基线为 `import_sites=6`、`literal_files=19`、`literal_hits=118`（词表版本见
`data/domain_boundary/finance_lexicon.json`）。随后核心直接 import 已降至 `0`；金融字面量
已降至 `3` 个文件、`9` 行。该机制防止债务增长，不等于完整的领域迁移已经完成。

本次将 Planner 的金融指标识别、年度期解析、结构化请求校验与 LLM 规划后的发行人身份
补全迁入 finance pack；Engine 将已解析的 pack 传给 Planner，注入中性 pack 的单测证明
该组合点不再隐式回退到 finance 实现。

数值引用的金融规则已从 core agent 模块迁入 finance pack。Evaluator 与 Reporter 经
`NumericCitationPolicy` 接收该规则，保留的旧模块仅是兼容门面，不能承载领域实现。
Researcher 的权威披露优先词表也由 pack 提供，通用检索路径不再内联财务报表字段。
金融 skill 的适用性词表与资源定位已迁入 finance pack；原路径仅经注册表保持兼容。
AKShare 与 fixture structured-data provider 的指标别名、默认指标和交易所标签也改由 pack
提供；二者原有的“营业总收入”归一化差异经独立方法保留。
结构化输出的财务指标声明模式与别名表路径同样经 pack 解析，通用输出层不再嵌入
金融指标或单位词表。
覆盖计算的同比识别与主营业务毛利率维度约束也已下沉至 pack，通用覆盖逻辑只组合
领域提供的匹配结果。
demo follow-up 的财务指标候选、口径变更文案也改由 pack 提供，且新增回归覆盖 finance
fallback 分支。

fixture 现从两份受跟踪 PDF 再生：贵州茅台年报第 6 页，以及宁德时代匈牙利项目公告的
第 1、2 页；每条均保存 PDF SHA-256 与页码。茅台数值另有 `page,x0,top,x1,bottom` bbox
及 `extract_tables()` 表格索引。数值 Evidence 与 SQLite 持久化、评测结果均携带该锚点；
主披露离线回归的 `bbox_resolution_rate` 为 `1.0`。年度指标优先读取表格单元格，无表格
索引的旧输入仍使用文本兼容回退。该指标仅用于可观测性，不参与评分门禁。pdfplumber 的
引入、许可证和回滚界限见同目录 ADR。算术拒绝现包含 `expected`、`actual`、`tolerance`
与 `source_locator`。B5 尚未结案的唯一流程项是将首次真语料门禁变红及逐条红→绿归因
完整归档到轮次报告；该归因现已记录于轮次审计材料，B5 已满足其离线验收门。

随后仓库所有者于 2026-07-28 对 B8 给予了覆盖性成本授权。三次受 10 CNY/次、30 CNY
全轮熔断约束的真实尝试，加一条 qwen3.7-plus 连通性探针，共记录 0.10164388 CNY。探针
及 LLM/judge 均成功；attempt-1 还实际使用 Tavily/CNINFO，但 AKShare 的 symbol resolve
有界失败并产生 degradation；attempt-2 的 reporter Evidence 保真合同拒绝输出；attempt-3
完成但实际 evidence 仍只有 CNINFO，未使用 AKShare。因此三层真实判据未满足，B8 为
`INCOMPLETE`，不是“管道已跑通”。脱敏原始记录保留在协作运行产物；DASHSCOPE key 建议
轮换，未在受管文档记录任何凭据字符。

## B1 运行作用域迁移（CLOSED）

provider 调用现在接收显式 per-call `RunToolContext`；Researcher 搜索配额、工具预算和
`BranchBudget` 归入 LangGraph `Runtime.context` 中的 `RunScope`。workflow engine 不再持有
这些 run 实例字段或运行锁，并发 8 个 fixture run 的预算快照、完成状态与报告均与串行
基线一致。把预算临时改回实例字段时该守卫失败。

`api/main.py` 复用 lifespan engine；`api/demo.py` 的锁保持 demo 队列串行语义。既有
strict-replay 路径指向没有调用缓存的 fake fixture，因而不能证明 CLI。现在的回归守卫先
录制 deterministic trajectory，再由实际 CLI strict replay，且断言 `reproduced` 和逐字报告
匹配；这修复了验证资产，不放宽 strict replay 合同。B1 的全部机器判据现为 PASS。

## B2 工作流拆分（CLOSED）

`workflow/engine.py` 已从 3,125 行拆至 857 行；节点、图装配、运行时包装、状态辅助和报告
装配被迁入边界明确的模块。`check_workflow_module_size.py` 同时实际断言 engine 不超过 900
行、每个 B2 提取模块不超过 600 行，避免只展示行数而不判定。图装配必须引用带 reducer 的
`ResearchGraphState`；一次错误地将其替成普通 `dict` 会使 LangGraph Send 扇出报
`InvalidUpdateError`，已修正并由完整门禁覆盖。

orchestration 的 replan 逻辑不再直接加载 finance pack。它只声明三个方法的窄
`ReplanDomainPolicy`，由 workflow 节点提供既有 `DomainPack`，因此金融文档类型选择与补齐
方向保持原行为，且 orchestration 对 workflow/domains 的反向直接依赖为 0。五个既有单测
只同步新增的显式 policy 参数，未删除断言或减少用例。新增 demo artifact parity 测试在两次
独立 fixture run 间逐字比较报告；完整门禁通过 584 项测试，golden 输出未变。

## B4 领域实现迁移（CLOSED）

核心侧金融字面量已降至 3 个文件、9 个命中；残留仅为报告格式化、不可变 golden 审计和
历史序列化兼容字段。`domain-boundary-residual.md` 逐项记载保留理由和移除条件，并由单测
将该表与 allowlist 逐行关联。`agents/` 不再含 `financial_*.py`。完整门禁通过 585 项测试，
golden 输出没有变化。

## B6 LLM 工具选择（CLOSED）

`complete_with_tools()` 以 provider-native `tools=` 调用复用既有 LLM 账本、预算、token、
成本与延迟记录。`LLM_TOOL_SELECTION_ENABLED` 默认为 `false` 且为 `content_affecting`；
关闭时 golden 输出逐字不变。开启时只向模型提供已登记且适用的 capability schema，未登记
名称被拒绝并记录 degradation event。

每个模型 tool-call 现在对应一个 `AgentDecision` 和一个带 `selection_only` 标记的轨迹项。
该标记保留选择序列的 strict-replay 防篡改约束，同时避免把模型建议伪造为已发生的外部
egress。工具预算仍由既有 `RunToolContext` 守卫执行：超限请求被拒绝，并在 tool trace 中
留下 `budget_exceeded` failure。默认值理由与将来转正条件见
`adr-llm-tool-selection.md`。
