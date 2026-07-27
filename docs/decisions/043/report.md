# 043：领域边界棘轮

043 首先把 concrete finance import 与金融字面量的基线测量变成受版本控制的离线守卫。
初始基线为 `import_sites=6`、`literal_files=19`、`literal_hits=118`（词表版本见
`data/domain_boundary/finance_lexicon.json`）。随后核心直接 import 已降至 `0`；金融字面量
已降至 `6` 个文件、`15` 行。该机制防止债务增长，不等于完整的领域迁移已经完成。

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
完整归档到轮次报告。

本轮未获真实 provider 的新增成本授权，因此不执行付费端到端运行。
