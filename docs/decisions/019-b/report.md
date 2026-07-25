# 任务卡 019-B 执行报告

日期：2026-07-25  
分支：`task/019b-preflight-facts`  
基线：`f08915c560d876c142914f070f894de9e3d8a722`  
结论：**B0–B7 COMPLETE；预登记 Branch B；STOP 交 PM，不得进入付费 019-C。**

## 1. 结果摘要

- 金钱成本：`¥0`。唯一网络阶段 B2 只调用 Tavily basic search，恰好 18 次；
  无 completion/LLM provider 调用。其余阶段零网络。
- 检索可达性：`REACHABLE=2`、`PARTIAL=4`、`UNREACHABLE=0`。
- 已修复：
  1. 重规划 query 不再泄漏内部 issue/置信度诊断，审计信息仍留在
     `AgentDecision`。
  2. LLM 报告读者层统一人民币和日期展示，并按
     `(entity, normalized_metric, period, scope)` 去重。
  3. strategy replay 不再只是标签；未实现的 mode 会 fail closed，对外文字已
     诚实降级。
- B6 零网络超集包：11 个目标 dark 开关全开，报告、结构化表、审计包、快照、
  轨迹齐全；引用闭合 `ok`；DecisionGate blocked=0；图契约通过。
- 最终闸门：350 tests、0 failures；Ruff 0.15.15；prompt drift、
  characterization、chaos、site build 全绿。
- 生产代码：新增 180 行、删除 35 行，共变更 215 行；距 350 行上界 135 行。
- `data/golden_set/`、`docs/evaluation.md`、`pyproject.toml` 均为 0 变更。

分支 B 的约束性结论是：**若不解决检索可达性，019-C 的负面结论将无法归因。**

## 2. B0：分支与基线

从 main HEAD `f08915c` 创建 `task/019b-preflight-facts`。提示词已逐字保存为
`_collab/019b_preflight_facts/prompt.md`。

基线原始摘要：

```text
Ran 347 tests in 16.021s

OK
ruff 0.15.15
All checks passed!
prompt drift guard passed: 5 prompts
Ran 2 tests
OK
Ran 8 tests
OK
files 13
validation ok
```

原始文件：`b0_full_tests.txt`、`b0_ruff_version.txt`、`b0_ruff.txt`、
`b0_prompt_drift.txt`、`b0_characterization.txt`、`b0_chaos.txt`、
`b0_build_site.txt`。

## 3. B1：生成机制勘查

LLM 路径入口为
`src/deepresearch_agent/agents/reporter.py:49 ReporterAgent.report()`；
存在 `llm_client` 时进入 `:135 _llm_report()`。后者读取
`prompts/reporter.md`，把 topic、plan、Evidence（含 numeric_fields）和
CriticReport 发给 LLM，要求返回
`src/deepresearch_agent/schemas.py:136 ReportDraft`。之后
`:293 _render_llm_report()` 用固定 Markdown 模板渲染。

### 3.1 一级章节完整表

| 章节 | 生成机制 | 数据来源 | 文件:行号 |
| --- | --- | --- | --- |
| 摘要 | LLM 生成结构化字段，再由模板渲染；空值时本地 fallback | `ReportDraft.summary` | `reporter.py:135–178, 293, 317–319` |
| 关键发现 | LLM 生成独立 claim 列表，模板逐条渲染/引用 | `ReportDraft.key_findings` | `schemas.py:138`, `reporter.py:321–340` |
| 详细分析 | LLM 生成按 sub-question 分组的独立 section 列表，模板按 plan 顺序渲染 | `ReportDraft.detailed_analysis` | `schemas.py:139`, `reporter.py:341–370` |
| 风险与限制 | 优先渲染 LLM 字符串列表；为空时机械使用 Critic issues | `ReportDraft.risks` / `CriticReport.issues` | `schemas.py:140`, `reporter.py:372–389` |
| 未验证假设 | LLM 生成 claim 列表；为空时模板输出固定无新增说明 | `ReportDraft.unverified_assumptions` | `schemas.py:141`, `reporter.py:391–407` |
| 参考来源 | 非 LLM；由 Evidence 的冻结脚注映射机械生成 | `build_footnote_maps(evidence)` | `reporter.py:299–301, 409–415` |

### 3.2 “关键发现”与“详细分析”是否消费同一列表

不是同一列表。它们属于同一个 `ReportDraft` 对象，但分别消费
`draft.key_findings` 与 `draft.detailed_analysis[].claims`。019-A A8 stub
之所以重复，是 stub 同时把相同金融事实放进这两个独立字段；不是 renderer
把一个列表渲染两次。

### 3.3 科学计数法与期间键路径

修复前，Evidence 的 `numeric_fields` 在 `reporter.py:151–164` 原样进入
Reporter LLM 输入；LLM/stub 返回的 `ReportClaim.text` 又在
`_render_claim()` 中直接进入正文。于是 `3.62013e+11元` 和 `20241231`
可作为普通文本穿透。修复后，`:418 _render_claim()` 在 `:436` 调用
`:461 _reader_text()`，只改变读者层字符串；Evidence/structured numeric
对象不变。

确定性 Reporter 另有 `:515 _evidence_claim_text()`，不是 A8 的 LLM 报告
重复路径，本卡没有把两条路径混称。

### 3.4 重规划污染路径

修复前，
`src/deepresearch_agent/orchestration/research_loop.py:262` 对 targeted
Critic issue 直接拼接：

```text
{sub_question.question} resolve {issue.issue_type}: {issue.message}
```

并额外拼接 `resolve critic evidence gap`。因此 issue type、message 和
置信度诊断直接成为检索工具输入。

修复后统一经过 `research_loop.py:53 build_replan_query()`；完整 issue
对象则由 `decision_context.py` 保留并进入 `AgentDecision.inputs`。

## 4. B2：Tavily 检索可达性探针

### 4.1 调用边界

```text
tavily_search_calls=18
question_count=6
result_count=90
```

- endpoint：仅 Tavily `POST /search`
- search depth：basic
- retry：0
- LLM/completion：0
- 货币支出：¥0；使用已配置的免费 basic credit 边界
- 原始响应：只在 ignored 路径；公开探针只留域名、标题、不超过 1,000
  字符摘录与 SHA-256

本轮没有打开计费控制台独立复核余额；可机械证明的是 task ledger 恰为 18 个
basic search credits、无 completion ledger 和无货币成本记录。

### 4.2 18 条实际查询

Q01：

1. `贵州茅台 2024 年年度报告 营业总收入 归母净利润 各自同比增速`
2. `贵州茅台 2024 年年报 茅台酒 系列酒 收入结构 亿元`
3. `贵州茅台 2024 年年度报告摘要 巨潮资讯 600519 营业总收入`

Q04：

1. `宁德时代 2024 年年度报告 营业收入 归母净利润 各自同比`
2. `宁德时代 2024 年营收下降利润增长 原材料价格 毛利率 成因`
3. `宁德时代 2024 年年度报告 巨潮资讯 300750 营业收入 毛利率`

Q16：

1. `2024 年全球动力电池装机量 宁德时代 比亚迪 市场份额 SNE Research`
2. `2024 年中国动力电池装车量 宁德时代 比亚迪 市占率 行业协会`
3. `宁德时代 比亚迪 2024 年全球动力电池市占率 第一 第二`

Q19：

1. `2024 至 2025 年中国创新药 License-out 交易总额 首付款 公司公告`
2. `2024 年恒瑞医药 GLP-1 海外授权 首付款 潜在总金额 公告`
3. `2025 年中国创新药 License-out 代表性交易 首付款 总金额 公司公告`

Q26：

1. `宁德时代 匈牙利工厂 2022 年公告 100GWh 开工 建设进展`
2. `宁德时代 匈牙利工厂 2024 至 2025 年建设进展 投产 已建成产能`
3. `CATL Hungary Debrecen factory official construction progress 2025 capacity`

Q28：

1. `2024 年光伏行业 自律 减产挺价 中国光伏行业协会 会议 倡议`
2. `2024 年光伏行业 防止内卷式恶性竞争 座谈会 企业减产行动`
3. `2024 年光伏企业 自律会议 控制产能 价格治理 实际执行`

### 4.3 逐题域名、判定和噪声

| 题号 | 唯一召回域名 | 判定与证据 | 主要噪声 |
| --- | --- | --- | --- |
| Q01 | baike.baidu.com, www.kkday.com, www.gzl.com.cn, you.ctrip.com, zh.wikipedia.org, jljcscyxs.mofcom.gov.cn, stcn.com, xueqiu.com, www.scribd.com, www.chnfund.com, huacheng.gz-cmc.com, www.21jingji.com, **www.moutaichina.com**, money.finance.sina.com.cn, pdf.dfcfw.com | **REACHABLE**。命中贵州茅台官网 2024 年年度报告；营业总收入、归母净利润、同比与茅台酒/系列酒收入可核验。 | “贵州”被误拆造成旅游/百科；内容平台与二手转载。 |
| Q04 | duplik-1252068037.cos.ap-beijing.myqcloud.com, pdf.dfcfw.com, **www.catl.com**, tdt.bocomgroup.com, www.cls.cn, m.bjnews.com.cn, www.21jingji.com, finance.sina.com.cn, zhuanlan.zhihu.com, zjic.zj.gov.cn, reportify-1252068037.cos.ap-beijing.myqcloud.com, static.cninfo.com.cn | **REACHABLE**。命中宁德时代官网 2024 年年报；精确业绩数值与原材料降价、售价调整、毛利改善解释可召回。 | 券商研报和新闻解释较多；官网长报告首段不一定落在目标页。 |
| Q16 | www.jitstech.com, m.cbea.com, finance.sina.com.cn, www.nbd.com.cn, www.heshengmade.com, m.chinabaogao.com, bg.qianzhan.com, tdt.bocomgroup.com, auto.jgvogel.cn, www.sohu.com, mp.m.ofweek.com, www.chnfund.com | **PARTIAL**。精确召回宁德时代 339.3GWh/37.9% 第一、比亚迪 153.7GWh/17.2% 第二，但未直达 SNE Research 原始发布。 | SNE 中文二次转述；旧协会数据、报告销售页。 |
| Q19 | library.emedclub.com, finance.sina.com.cn, www.phirda.com, www.pharnexcloud.com, www.stcn.com, bydrug.pharmcube.com, finance.sina.cn, www.cls.cn, www.hengrui.com, www.pharmcube.com, www.tfcaijing.com, www.cbpfcn.com | **PARTIAL**。召回恒瑞 GLP-1 潜在总额、首付款/近期里程碑与多个 2025 交易示例，但未稳定直达至少两笔公司公告原文。 | 数据库营销页、行业回顾、媒体转载；总额/首付款/里程碑混用。 |
| Q26 | **www.catl.com**, www.stcn.com, m.energytrend.cn, libattery.ofweek.com, m.caixin.com, wap.eastmoney.com, www.21jingji.com, www.nengyuanjie.net, finance.sina.com.cn, www.chinadaily.com.cn, cnevpost.com, www.green-forum.eu, www.electrive.com, baike.baidu.com | **PARTIAL**。直达 2022 年宁德时代公告与 100GWh 规划；2025 年末建设/投产状态仍主要依赖媒体。 | 2025 投产与 2026 初投产预测冲突；英文二手与百科。 |
| Q28 | www.film-expo.com, www.fxbaogao.com, paper.people.com.cn, www.chinapv.org.cn, www.gessey.com, stcn.com, epaper.ceic.com, news.qq.com, www.news.cn, pdf.dfcfw.com, www.cls.cn, wap.9fzt.com, www.nationalee.com | **PARTIAL**。召回协会域名、10 月反内卷座谈会与新华社事件转述，但企业实际减产执行无一手闭环。 | 乱码报告、报告销售页、事后报道；倡议/共识/实际执行混淆。 |

完整的 90 条标题、摘录和 SHA-256 见 `retrieval_reachability.md`。

### 4.4 预登记分支

`REACHABLE=2 < 4`，故进入 Branch B。B3–B7 按卡继续完成；之后 STOP。

## 5. B3：重规划 query 修复

### 5.1 修复前后实际文本

修复前（019-A A8）：

```text
宁德时代 2024 年业绩、欧洲工厂扩张与风险有哪些可核验事实？
resolve unverified_projection: Projection claim has low extraction confidence:
宁德时代 欧洲工厂 投产日期为2025年6月。
```

修复后（B6 实际全图第二轮）：

```text
宁德时代 2024 年业绩、欧洲工厂扩张与风险有哪些可核验事实？
官方披露 建设进展 实际日期
```

第二条 fallback：

```text
宁德时代 2024 年业绩、欧洲工厂扩张与风险有哪些可核验事实？
官方来源 补充核验
```

长度上限定为 180 字符：足以承载中文实体、期间、口径和缺口方向，同时避免把
长 Critic message 或 prompt 片段继续扩散给检索引擎。

### 5.2 实际决策链仍可审计

轨迹中的 `research_replan`：

```json
{
  "unresolved_critic_issues": [{
    "issue_id": "critic-1",
    "issue_type": "unverified_projection",
    "message": "Projection claim has low extraction confidence: 宁德时代 欧洲工厂 投产日期为2025年6月。",
    "severity": "medium",
    "sub_question_ids": ["catl_performance"]
  }],
  "outcome": "refined_queries={'catl_performance': ['宁德时代 2024 年业绩、欧洲工厂扩张与风险有哪些可核验事实？ 官方披露 建设进展 实际日期', '宁德时代 2024 年业绩、欧洲工厂扩张与风险有哪些可核验事实？ 官方来源 补充核验']}"
}
```

内部信息没有被删除，只从 tool query 移到决策输入。

### 5.3 六题自动重规划与 B2 对照

修复函数实际生成：

```text
Q01: 贵州茅台 2024 年年度报告营业总收入与归母净利润 公司官网 年报 原始口径 同比 核验
Q04: 宁德时代 2024 年营业收入下降与归母净利润增长 公司官网 年报 原材料价格 毛利率 成因 核验
Q16: 宁德时代与比亚迪 2024 年全球动力电池装机量和市场份额 SNE Research 原始发布 排名 统计口径
Q19: 中国创新药 2024 至 2025 年海外授权代表交易 公司公告 总金额 首付款 近期里程碑 逐笔核验
Q26: 宁德时代匈牙利工厂 2022 至 2025 年规划与建设进展 公司官方披露 100GWh 实际投产日期
Q28: 2024 年光伏行业反内卷自律与减产执行 行业协会及公司官方披露 实际执行 产能 价格
```

长度依次为 45、49、55、51、51、43，均低于 180。B2 的 18 条是人工设计的
探针，本来就是自然语言；修复后的自动 query 与其结构一致，但明确补上
“公司官网/原始发布/公司公告/实际执行”等缺口方向。二者均无内部诊断词。

## 6. B4：报告读者层修复

### 6.1 实际报告片段

修复前（019-A A8 完整关键发现节）：

```markdown
## 关键发现
- 宁德时代 2024 年累计营业收入为 3620.13 亿元。 [^1]
- 宁德时代 欧洲工厂 投产日期为2025年6月。 [^2]
- 宁德时代 20241231 累计营业收入为3.62013e+11元。 [^3]
```

修复后（B6 完整关键发现节）：

```markdown
## 关键发现
- 宁德时代2024年12月31日累计营业收入为3620.13亿元。 [^3]
- 宁德时代2024年12月31日累计归母净利润为507.4468亿元。 [^5]
```

修复后的详细分析节：

```markdown
## 详细分析
### 宁德时代 2024 年业绩、欧洲工厂扩张与风险有哪些可核验事实？
- 欧洲工厂投产日期仍是预测性披露，应以最新官方建设进展核验。 [^2]
```

### 6.2 实现边界

- `_reader_text()` 只转读者字符串：
  - `3.62013e+11元` → `3620.13亿元`
  - `20241231` → `2024年12月31日`
- `metric_fact_keys()` 复用既有金融 alias 和 structured extraction，
  生成 `(entity, normalized_metric, normalized period, scope)`。
- 年报期间 `20241231` 归一为 `2024`，使“元”和“亿元”的同一年度事实可去重。
- `seen_fact_keys` 跨关键发现与详细分析共享；只跳过正文重复，不删除 Evidence、
  structured row、脚注映射或审计数据。
- Reporter prompt 从 1.0.0 升到 1.1.0，要求关键发现负责结论，详细分析负责
  支撑、含义、矛盾和限制；真实模型遵循程度仍需后续实测。

## 7. B5：strict / strategy 语义诚实化

选择路线甲。原因：当前没有经过定义和审计的策略级宽松键；在本卡 350 行约束内
临时设计它会扩大到真实轨迹语义。最小诚实行为是只承诺 strict，并明确拒绝
strategy。

### 7.1 修改前命中

- `src/deepresearch_agent/trajectory.py`：`ReplayResult.mode` 接受
  `Literal["strict", "strategy"]`。
- `scripts/replay_trajectory.py`：CLI `--mode` 可选 strict/strategy。
- `tests/integration/test_trajectory_replay.py`：用 strategy 标签测试 cache miss，
  但与 strict 无匹配差异。
- `docs/architecture.md:223–224`：宣称 strategy replay 在未录制调用停止。
- `docs/trajectory_harness.md:9`：宣称 strategy replay 可预声明 required calls。
- `docs/decision_weaving.md:70`：宣称策略回放遇未录制调用停止。
- `AGENTS.md:7`：项目状态宣称已有 fixture 严格/策略回放。
- `docs/decisions/019-a/report.md` 与 `work_orders.md`：已如实记录两者无不同
  语义，属于历史诚实证据，未篡改。

### 7.2 修改后行为与全部相关命中

- `ReplayResult.mode` 只允许 `strict`。
- `replay_trajectory(..., mode!="strict")` 抛
  `ValueError("strategy replay is not implemented; use strict replay")`。
- CLI 删除 `--mode`，只执行 strict。
- 测试明确验证 strategy 被拒绝。
- architecture、trajectory harness、decision weaving 和 AGENTS 均写明
  strategy-level replay 未实现。
- 历史 019-A report/work order 继续写明当时缺口。

最终泛化搜索涉及文件：

```text
AGENTS.md
docs/architecture.md
docs/decision_weaving.md
docs/decisions/019-a/report.md
docs/decisions/019-a/work_orders.md
docs/trajectory_harness.md
src/deepresearch_agent/trajectory_replay.py
tests/integration/test_trajectory_replay.py
```

所有命中都与“strict 已实现、strategy 未实现”一致。

## 8. B6：零网络超集端到端复验

运行条件：`DEEPRESEARCH_MODE=llm`，手写 completion，fixture search/structured
provider，11 个目标开关全开。

完整机械摘要：

```text
network_calls=0
execution_mode=llm
superset_flags_enabled=11
status=done
missing_sections=0
cited_conclusion_bullets=3
uncited_conclusions=0
scientific_notation_hits=0
raw_period_key_hits=0
duplicate_revenue_fact_count=0
section_conclusion_sets_equal=False
structured_complete=true
metric_rows=4
timeline_events=6
risk_items=1
audit_citation_closure=ok
snapshot_claims=6
snapshot_manifest_ref=True
trajectory_exists=True
agent_decisions=16
decision_gate_blocked=0
graph_contract_validation=passed_at_engine_init
```

产物存在性复核：

```text
INJECTION_GUARD_ENABLED=true
CONTEXT_PACKER_ENABLED=true
TRAJECTORY_RECORD_ENABLED=true
BRANCH_BUDGET_ENABLED=true
RESEARCH_LOOP_ENABLED=true
PRIOR_MEMORY_ENABLED=true
DECISION_WEAVING_ENABLED=true
NUMERIC_CHECK_ENABLED=true
DYNAMIC_CAPABILITY_ENABLED=true
REFLECTION_ENABLED=true
SKILL_PACKS_ENABLED=true
artifact:report.md=exists
artifact:structured.json=exists
artifact:structured.xlsx=exists
artifact:audit_bundle/manifest.json=exists
artifact:research_snapshot.json=exists
trajectory_count=1
ledger_rows=4
trajectory_llm_calls=6
trajectory_decisions=16
snapshot_manifest_ref=true
```

脚本打印 `snapshot=None` 是 `save_research_snapshot()` 的返回值约定，不是文件
缺失；后续存在性与 JSON 检查证明 `research_snapshot.json` 存在且包含 manifest
引用。trajectory 的 6 条 LLM trace 中有 2 条是 Reflector placeholder，因此
运行 ledger 为 4 行；本轮只证明 stub 全图和轨迹契约，不把 placeholder 称为
真实模型调用。

首次 B6 尝试在图执行前被 config fail-fast 拒绝，因为进程环境未设置 stub key；
没有 provider 或 graph call。补齐显式本地 stub key 后成功。失败现场保存在
`b6_failed_config/`，未把它伪装成成功运行。

## 9. 守卫测试与反向验证

| 守卫 | 防止的回归 | 去掉修复时的验证 |
| --- | --- | --- |
| `test_replan_query_guard.py` | query 包含 `resolve `、`unverified_`、`_gap`、`confidence:`、`Projection claim`、`critic`、`issue_id`、ASCII snake_case，或超过 180；同时要求 issue 可追溯 | monkeypatch 回旧式污染 builder 后 1 failure |
| `test_report_reader_guard.py` | 科学计数法、原始期间键、重复金融事实；并检查原 numeric value 未变 | monkeypatch `_reader_text` 为 identity 后 1 failure |
| `test_trajectory_replay.py::test_strategy_replay_is_rejected_as_unimplemented` | 未实现 mode 被继续接受或仅换标签 | monkeypatch 为接受 strategy 后 1 failure |

反向验证原始输出：

```text
B3_without_query_sanitizer: failures=1 errors=0
B4_without_reader_normalization: failures=1 errors=0
B5_without_strategy_rejection: failures=1 errors=0
guard_mutation_check=passed
```

### 9.1 所有测试资产改动与理由

- `tests/unit/test_replan_query_guard.py`：新增违反即失败的 query/审计联合守卫。
- `tests/unit/test_report_reader_guard.py`：新增读者文本、事实去重和原值不变守卫。
- `tests/integration/test_trajectory_replay.py`：把原“strategy cache miss”测试
  改名为 strict cache miss，并新增 strategy 拒绝测试；这是收紧能力，不是弱化。
- `tests/unit/test_decision_weaving.py`：预期值从内部诊断串改为自然查询，并新增
  issue id 检查；审计断言更强。
- `tests/unit/test_numeric_consistency.py`：预期 query 改为自然“官方数据/计算口径/
  单位/核验”；数值矛盾触发断言不变。
- `tests/unit/test_reflection.py`：不再要求 bad.example 进入 query，改为断言它不
  泄漏到 query 且仍保留在 decision inputs；保留审计、收紧工具边界。
- `tests/golden_output/finance_structured.json`、
  `tests/golden_output/wealth_research.json`：只同步 Reporter prompt SHA
  `01a322...` → `e4f904...`；两次 characterization 的其他字节未变化。这是
  provenance 同步，不是修改冻结 `data/golden_set/` 或降低断言。

没有删除、skip、xfail 测试，也没有降低 Ruff。

## 10. 生产代码行数与冻结资产

```text
66   6  src/deepresearch_agent/agents/reporter.py
7    1  src/deepresearch_agent/orchestration/decision_context.py
78  27  src/deepresearch_agent/orchestration/research_loop.py
24   0  src/deepresearch_agent/structured_output.py
1    1  src/deepresearch_agent/trajectory.py
4    0  src/deepresearch_agent/trajectory_replay.py

added=180 deleted=35 changed=215 remaining=135
```

受限路径检查：

```text
git diff --exit-code main -- data/golden_set docs/evaluation.md pyproject.toml
# exit 0, no output
```

无冻结 Golden Set 元数据变更申报；`data/golden_set/` 完全未改。

## 11. 最终绿灯闸门

命令：

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
DEEPRESEARCH_SEARCH_PROVIDER=fixture \
DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=fixture \
DEEPRESEARCH_MODE=deterministic \
DEEPRESEARCH_STORAGE_PATH=_collab/019b_preflight_facts/final_research.db \
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff --version
PYTHONPATH=src .venv/bin/python -m ruff check src tests scripts
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python scripts/check_prompt_drift.py
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python -m unittest tests.unit.test_snapshot_run -v
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
DEEPRESEARCH_SEARCH_PROVIDER=fixture \
DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=fixture \
.venv/bin/python -m unittest discover -s tests/chaos -v
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python scripts/build_site.py
```

原始摘要：

```text
Ran 350 tests in 16.005s

OK
ruff 0.15.15
All checks passed!
prompt drift guard passed: 5 prompts
Ran 2 tests in 0.109s
OK
Ran 8 tests in 0.265s
OK
built <repo>/site/dist
files 13
validation ok
```

`AGENTS.md` 诚实性补漏提交前又完整执行一次：

```text
Ran 350 tests in 15.961s
OK
ruff 0.15.15
All checks passed!
prompt drift guard passed: 5 prompts
Ran 2 tests in 0.083s
OK
Ran 8 tests in 0.254s
OK
files 13
validation ok
```

完整原始输出保存在 `final_*` 与 `precommit4_*`。

## 12. 对 019-C 的影响和 PM 选项

详见 `impact_on_019c.md`。范围估计如下，均不是实施授权：

1. 更换/增加检索 provider：3–5 个实现/配置/测试文件，约 120–220 行生产代码，
   再跑同一 18-query 零 LLM 对照。
2. 增加一手源直连：首批交易所/巨潮与公司公告约 4–7 个文件、180–320 行；
   若含协会和海外官方渠道可能超过单卡上限，应拆卡。
3. 替换四道 PARTIAL 题：约 2–4 个题集/预登记/审计文档、无生产代码，但必须
   重新冻结并申报外推边界。

建议 PM 先选择目标：验证“现有 Tavily 边界内 Agent 增益”可考虑换题；验证
“真实 A 股一手披露研究能力”应优先评估直连。任何方案均应先把同口径门禁恢复到
`REACHABLE >= 4`，再授权 019-C。

## 13. 遗留与风险

1. 四题仍为 PARTIAL；这是本轮 STOP 的决定性阻断。
2. Reporter prompt 的章节职责只在 stub 和机械结构上验证；真实模型是否稳定遵循
   尚无证据。本卡不以此为由推迟可在 ¥0 修复的 renderer 问题。
3. 人民币文本正则目前面向“数值+元”形式；带千分位、币种前缀或复杂区间的真实
   模型文本尚未覆盖。
4. 事实去重依赖 Evidence 的数字五元素和既有 alias；无 numeric_fields 的同义
   自然语言事实不会被此机械键合并。
5. strategy replay 明确未实现；真实轨迹 strict replay 仍需 019-C 另行授权。
6. B6 LiteLLM import 给出缺少 botocore 的 Bedrock/SageMaker event-stream warning；
   本轮未用这两个 provider，不构成新增依赖理由。
7. B2 的“免费”基于已配置免费 basic credit 边界与本轮零金额 ledger，不是 billing
   UI 截图证明。

## 14. 诚实声明

### 机械验证

- 18 次 Tavily、90 条结果、无 completion 调用。
- query 禁词/长度、决策 issue 溯源。
- B6 network_calls=0、产物存在、引用闭合、blocked=0、契约通过。
- 报告科学计数法/原始期间键/重复事实计数与章节集合差异。
- strategy 被拒绝、全仓剩余表述一致。
- 350 tests/0 failures、Ruff 与其余闸门。
- 生产代码 215/350 行、受限路径 0 变更。

### 人工判读

- 六题 REACHABLE/PARTIAL 分类。
- 噪声类型及“一手闭环是否足够”的解释。
- 三种 019-C 处置的范围估计。

### 尚无证据支持

- Tavily 以外 provider 会把 REACHABLE 提升到多少。
- 一手直连的真实实现成本和许可/反爬稳定性。
- 真实 deepseek-v4-flash 会稳定遵循新 Reporter prompt。
- 本轮报告修复会改善任何 judge 分数。
- 尚未实现的 strategy-level replay 的正确宽松键应是什么。

## 15. 自检

- 没有用“等真实模型”推迟可在 ¥0 处理的 query 污染、读者渲染或能力表述缺陷。
- 没有把 B2 可达性问题留给付费实验承担。
- 没有把 fixture stub 的结构通过外推成真实模型判断质量。
- 没有为通过测试修改 Golden Set、evaluation 定义、依赖或默认开关。
- 没有实施 live adapter、双臂候选注入、策略回放或真实 provider replay。
- 没有自行修改 019-C 预算上限，也没有替 PM 选择 provider/直连/换题。

## 16. 提交与 diff 原始输出

`git log --oneline main..HEAD`：

```text
0f6181e docs: mark strategy replay unimplemented
6273e64 fix: reject unimplemented strategy replay
d9023de fix: normalize reader-facing financial reports
0bcc85b fix: keep audit diagnostics out of search queries
```

`git diff main --stat`：

```text
 AGENTS.md                                          |   2 +-
 docs/architecture.md                               |   4 +-
 docs/decision_weaving.md                           |   3 +-
 docs/trajectory_harness.md                         |  14 +--
 prompts/registry.json                              |   4 +-
 prompts/reporter.md                                |   3 +
 scripts/replay_trajectory.py                       |   5 +-
 src/deepresearch_agent/agents/reporter.py          |  72 ++++++++++-
 .../orchestration/decision_context.py              |   8 +-
 .../orchestration/research_loop.py                 | 105 ++++++++++++----
 src/deepresearch_agent/structured_output.py        |  24 ++++
 src/deepresearch_agent/trajectory.py               |   2 +-
 src/deepresearch_agent/trajectory_replay.py        |   4 +
 tests/golden_output/finance_structured.json        |   2 +-
 tests/golden_output/wealth_research.json           |   2 +-
 tests/integration/test_trajectory_replay.py        |  16 ++-
 tests/unit/test_decision_weaving.py                |   8 +-
 tests/unit/test_numeric_consistency.py             |   2 +-
 tests/unit/test_reflection.py                      |  10 +-
 tests/unit/test_replan_query_guard.py              | 122 ++++++++++++++++++
 tests/unit/test_report_reader_guard.py             | 137 +++++++++++++++++++++
 21 files changed, 489 insertions(+), 60 deletions(-)
```

## 17. 最终处置

**Branch B / STOP。** 工程修复与零成本验证均已完成并提交，但付费 019-C 不得
继续。等待 PM 在“更换 provider / 增加一手源直连 / 替换题集”之间作出明确选择。

