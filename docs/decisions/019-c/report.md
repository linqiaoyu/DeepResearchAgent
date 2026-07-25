# 019-C 实验仪器可行性与证据质量报告

日期：2026-07-25  
分支：`task/019c-instrument-viability`  
金钱成本：`¥0`  
LLM provider 调用：`0`

## 总判定

**不得推进付费实验。**

本卡同时进入预登记分支 B、C、D、F：

- B：充分性尺子在一般构造输入上会动，但在 019-B stub 与付费实验预期的“继续增加已饱和证据、critic issue 未解决”范围内不动；该因变量不能把候选策略效果与离散 issue 是否恰好消失区分开，实验无法归因。
- C：`max_iterations=2` 只有 `2/4` 类非零反思信号；机械预设“至少 `3/4` 类非零且出现跨轮演化”下，深度 3 才达到最低信息量，工具调用约为深度 2 的 `1.56x`。
- D：四个数值观测之间没有同口径可校验关系，`checks=0` 是正确行为；最小完整增长关系会触发 `checks=1`。
- F：冻结后的 APBEC 宏平均为 `0`，`0/6` 题达到 `2/3`；一手正文闭合基础不成立。

019-B 的 `REACHABLE=2 < 4` 与 STOP 原地有效，本卡没有修改、重评或替代。

## C0：基线

- 分支从 main `71939f5` 创建。
- 公开路径存在 `docs/decisions/019-a/` 与 `docs/decisions/019-b/`。
- Python unittest：`Ran 350 tests in 15.812s`，`OK`。
- Ruff：`ruff 0.15.15`，`All checks passed!`。

## C1：充分性指标灵敏度

### 实现位置与完整公式

实现位于 `src/deepresearch_agent/orchestration/research_loop.py:130` 的 `evaluate_research_sufficiency`。

对每个子问题 `q`，默认阈值为：

- 最少证据数 `E*=2`；
- 最少独立域名数 `D*=2`；
- 最低平均置信度 `C*=0.7`；
- 最大新鲜度年龄 `F*=365` 天；
- 最大未解决 Critic issue 数 `I*=0`；
- 必须覆盖反例。

六个分量为：

1. `e_q = min(E_q / E*, 1)`；
2. `d_q = min(D_q / D*, 1)`；
3. `c_q = min(C_q / C*, 1)`；
4. `f_q = 1[freshest_age_q != None and freshest_age_q <= F*]`；
5. `i_q = 1[unresolved_issues_q <= I*]`；
6. `k_q = 1[不要求反例 or 已覆盖反例]`。

若共有 `N` 个子问题，则：

`score = round((Σ_q(e_q+d_q+c_q+f_q+i_q+k_q)) / (6N), 6)`

`sufficient` 不是按总分阈值判断，而是要求每个子问题均没有任何 gap。

### 0.833333 的逐分量机械还原

019-B stub 两轮的实际状态并不是“Evidence 从 5 增到 9”；增长的是累计 tool call，去重后的 Evidence 两轮均为 `6`。实际分量如下：

| 分量 | 迭代 1 实值 | 迭代 2 实值 | 分量分数 | 不变原因 |
| --- | ---: | ---: | ---: | --- |
| Evidence 数 | 6 | 6 | `min(6/2,1)=1` | Evidence 去重后未增加，且早已饱和 |
| 独立来源域 | 4 | 4 | `min(4/2,1)=1` | 未增加，且早已饱和 |
| 平均置信度 | 0.851667 | 0.851667 | `min(.851667/.7,1)=1` | 未增加，且早已饱和 |
| 最新证据年龄 | 43 天 | 43 天 | `1` | 均小于 365 天 |
| 未解决 Critic issue | 1 | 1 | `0` | 默认上限为 0，issue 未消失 |
| 反例覆盖缺失 | false | false | `1` | 已覆盖 |

因此两轮均为 `(1+1+1+1+0+1)/6 = 0.833333`。tool call 从 5 增至 9 不能直接推出 Evidence 增加；本卡用状态对象核对后纠正了该前提。

### 零网络灵敏度实验

| 构造输入变化 | 分数 | 相对上一行 |
| --- | ---: | ---: |
| 无 Evidence；0 域；置信度 0；无新鲜度；0 issue；缺反例 | 0.166667 | 基线 |
| 1 条 Evidence、1 域、置信度 .35、年龄 24 天 | 0.583333 | +0.416666 |
| 增至 2 条 Evidence、仍 1 域 | 0.666667 | +0.083334 |
| 增至 2 个独立域 | 0.750000 | +0.083333 |
| 平均置信度增至 .70 | 0.833333 | +0.083333 |
| 加入反例覆盖 | 1.000000 | +0.166667 |
| 加入 1 个未解决 issue | 0.833333 | -0.166667 |
| issue 保留，再增至 3 条/3 域/.80 | 0.833333 | 0 |

### 判定

尺子在未饱和输入和 issue 状态变化时会动；019-B stub 恰好位于五个分量饱和、唯一 issue 分量为 0 的平台区。付费实验预期比较“不同重规划候选带来的增量证据”，但若增量只落在已饱和分量且未立即消除 issue，因变量必定不动。因此在本次预期变化范围内判定为**不可动，进入分支 B**。

未擅自修改指标语义。建议交 PM 二选一：

1. 先把实验因变量改为连续的原子口径闭合增量、有效新 Evidence 增量或 issue 证据支持度，再重新预登记；预计修改 `ResearchSufficiency` 输出、轨迹摘要、报告与定向测试，约 80–140 行生产代码。
2. 保留现指标，但把实验假设限定为“候选能否消除指定 Critic issue”，并把 issue 消除设为主要因变量；这属于实验目标重定义，不是代码修补。

### 守卫

`tests/unit/test_research_loop.py::test_sufficiency_score_is_sensitive_before_components_saturate` 断言从 1 条/1 域增到 2 条/2 域时分数由 `0.833333` 增至 `1.0`。移除 Evidence/域名比例分量或把二者错误锁死为常量时该断言失败。

## C2：反思器输入信息量

### 019-B stub 的完整实际输入 JSON

```json
{
  "deterministic_signals": {
    "persistently_weak_subquestions": [],
    "repeatedly_ineffective_sources": [],
    "repeated_critic_issue_types": {
      "unverified_projection": 2
    },
    "ineffective_replanning_iterations": [
      2
    ]
  },
  "trajectory_summary": {
    "run_id": "<run-id>",
    "tool_call_count": 9,
    "node_transition_count": 16,
    "decision_types": [
      "bounded_loop_control",
      "branch_budget_allocate",
      "branch_budget_reallocate",
      "capability_selection",
      "numeric_consistency_scan",
      "procedural_memory_write",
      "reflection_signal_extraction",
      "research_replan",
      "skill_load",
      "skill_selection"
    ],
    "node_names": [
      "entry",
      "planner",
      "research_prepare",
      "research_one",
      "research_join",
      "extractor",
      "critic",
      "research_loop_decide",
      "reflector",
      "research_refine",
      "research_prepare",
      "research_one",
      "research_join",
      "extractor",
      "critic",
      "research_loop_decide"
    ]
  }
}
```

机械统计采用 `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`：

- 非零信号类别：`2/4`；
- 轨迹摘要字段数：`5`；
- 轨迹摘要内容长度：`597` 字符；
- 完整请求：`816` 字符。

### 深度对照

| max_iterations | 实际轮次 | 四类计数（弱项/无效源/重复 issue/无效重规划） | 非零类别 | 摘要字段/字符 | 总字符 | tool calls | 停止原因 |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |
| 2 | 2 | `0/0/1/1` | 2 | `5/597` | 816 | 9 | `max_iterations` |
| 3 | 3 | `1/0/1/2` | 3 | `5/722` | 961 | 14 | `max_iterations+no_progress_window` |
| 4 | 3 | `1/0/1/2` | 3 | `5/722` | 961 | 14 | `no_progress_window` |

### 判定

本卡在测量前采用“至少 `3/4` 类非零信号，并且信号出现跨轮演化”作为一次有意义 LLM 推理的最低信息量判断依据。深度 2 只有重复 issue 与单次无效重规划，无法区分持续弱项；信息不足。深度 3 首次出现持续弱子问题，并形成两次无效重规划，达到最低标准。深度 4 被 no-progress window 截止于第 3 轮，没有新增信息。

若 PM 选择提高到 3，stub 下 Reflector/研究轮次成本约为 `3/2=1.50x`，tool call 为 `14/9=1.56x`。这只是 fixture 的相对估计，不是付费金额预测。未修改默认值、预登记参数或四类输入边界，进入分支 C 交 PM。

## C3：数值自洽校验空转

实现位于 `src/deepresearch_agent/agents/numeric_checker.py:45` 的 `NumericConsistencyChecker`，入口 `check` 位于第 65 行。

| 关系 | 触发前置条件 |
| --- | --- |
| 增长率 | claim metric 匹配“基础口径 + 同比/环比 + 增长率/增速”；同 entity/scope；当前基础口径与 claim 同期；上期基础口径可由同比/环比推导；上期值非 0 |
| 占比 | metric 可解析为“分子占分母”并可带占比/比例/比重后缀；同 entity/period/scope；分子分母单位可换算；分母非 0 |
| 合计 | claim metric 恰有一个 `=`，一侧是至少两个 `+` 分量；各分量同 entity/period/scope；单位可换算到合计口径 |
| 单位换算 | 至少两个观测具有相同 entity、normalized_metric、period、scope；单位属于支持的货币或百分比体系；两者单位不同 |

四个实际观测为：

| 来源 | metric | period | scope | value/unit |
| --- | --- | --- | --- | --- |
| structured | 归母净利润 | 20241231 | 累计 | 50744680000 元 |
| structured | 营业收入 | 20241231 | 累计 | 362012600000 元 |
| text | 归母净利润 | 2024 | 累计 | 507.45 亿元 |
| text | 营业收入 | 2024 | 累计 | 3620.13 亿元 |

逐条件结果：

- 增长率：四个 metric 均不匹配增长关系名，false；
- 占比：四个 metric 均不含“占”，false；
- 合计：四个 metric 均不含 `=` 与 `+`，false；
- 单位换算：同 metric 的两条记录 entity/scope 可匹配、单位可换算，但 period 分别为 `20241231` 与 `2024`，完整分组键不相同，false。

因此 `numeric_observation_count=4, check_count=0` 是 **(a) 正确行为**。没有放宽 period 或 scope 来制造校验。最小守卫构造“本期基础值 + 上期基础值 + 同比增长率 claim”，实际得到 `check_count=1, issues=0`，证明校验器可用。

`tests/unit/test_numeric_consistency.py::test_complete_growth_relationship_triggers_a_numeric_check` 防止完整增长关系被静默跳过。将 `_GROWTH_RE` 置为永不匹配、删去当前/上期查找或不记录 check decision 时，该测试对 `check_count == 1` 的断言失败。

## C4：一手来源读取能力

原规则位于 `src/deepresearch_agent/tools/capability_selector.py:17-30`；原先 `financial_metric` 只配置 `structured_data_provider + web_search`。从按类型最小选择与 fallback 结构推断，其设计意图是避免无关能力调用；代码没有给出“financial 不应读原文”的业务理由。在一手验证场景中，Tavily snippet 不是正文，无法说明不 fetch 时如何形成一手证据，因此判定为缺陷。

修复后：

- `financial_metric` 与 `event` 规则选择 `web_fetch`，narrative/price 不无条件选择；
- `CapabilityRegistry` 将 fetch 明确声明适用于 event、financial_metric、verify；
- 决策仍由 `AgentDecision` 记录，criterion 说明一手正文理由并经过 DecisionGate；
- Researcher 仅在动态能力开关启用且选择含 fetch 时抓取，fetch 计入分支预算；
- Tavily provider 实现带 timeout/retry 的 GET 抓取；
- 开关关闭的既有确定性路径不变。

### 修复前实际决策

```json
{
  "alternatives_considered": [
    "skill.finance.metric_normalization",
    "structured_data_provider",
    "web_fetch",
    "web_search"
  ],
  "criterion": "apply configured rule for type=financial_metric and keep only capabilities declared applicable by the registry",
  "decision_type": "capability_selection",
  "inputs": {
    "candidate_capabilities": [
      "skill.finance.metric_normalization",
      "structured_data_provider",
      "web_fetch",
      "web_search"
    ],
    "fallback": false,
    "rejected_capabilities": [
      "skill.finance.metric_normalization",
      "web_fetch"
    ],
    "selected_capabilities": [
      "structured_data_provider",
      "web_search"
    ],
    "sub_question_id": "catl_performance",
    "sub_question_type": "financial_metric"
  },
  "iteration": null,
  "made_by": "ResearcherAgent",
  "outcome": "selected=['structured_data_provider', 'web_search']",
  "timestamp": "2026-07-25T01:47:40.590020Z"
}
```

### 修复后实际决策

```json
{
  "alternatives_considered": [
    "skill.finance.metric_normalization",
    "structured_data_provider",
    "web_fetch",
    "web_search"
  ],
  "criterion": "apply configured rule for type=financial_metric and keep only capabilities declared applicable by the registry; web_fetch is required to read first-party disclosure text for financial or event verification",
  "decision_type": "capability_selection",
  "inputs": {
    "candidate_capabilities": [
      "skill.finance.metric_normalization",
      "structured_data_provider",
      "web_fetch",
      "web_search"
    ],
    "fallback": false,
    "rejected_capabilities": [
      "skill.finance.metric_normalization"
    ],
    "selected_capabilities": [
      "structured_data_provider",
      "web_fetch",
      "web_search"
    ],
    "sub_question_id": "catl_performance",
    "sub_question_type": "financial_metric"
  },
  "iteration": null,
  "made_by": "ResearcherAgent",
  "outcome": "selected=['structured_data_provider', 'web_fetch', 'web_search']",
  "timestamp": "2026-07-25T10:33:01.453563Z"
}
```

### 预登记外真因授权使用

实现 fetch 后暴露两个与目标直接相关的真因，依据铁律 7 当场修复：

1. 原 Researcher 即使“选择” fetch 也没有执行 fetch。证明是新增执行守卫在接线前观察不到 fetch tool event。修复为 search result 逐条 hydrate。
2. 下一轮分支预算错误使用累计 `allocated_calls` 而非当前 `remaining_calls`，fetch 加入后出现分配 14、实际剩余 10。修复为基于预算快照的 remaining 分配；预算上界未提高。

## C5：查询生成与 019-B 人工基准

生成器位于 `src/deepresearch_agent/orchestration/research_loop.py:48` 的 `build_replan_query`。它从 `SubQuestion.structured_data_requests` 提取 company/symbol/metric/period，题面只提供去问句词与标点后的主题 facet，再拼目标文档方向；没有题号硬编码。无 symbol 的已知 company 使用“公司”作为最低限度消歧标识。既有 180 字符上限和内部禁词表未放宽。

下表为零网络离线生成；左列是 Agent，右列是 019-B 人工基准：

| ID | Agent 生成 | 019-B 人工基准 |
| --- | --- | --- |
| Q01-1 | 贵州茅台 600519 营业总收入 归母净利润 2024 贵州茅台2024年度业绩 归母净利润及各自同比增速 以及茅台酒与系列酒的收入结构 年度报告 | 贵州茅台 2024 年年度报告 营业总收入 归母净利润 各自同比增速 |
| Q01-2 | 贵州茅台 600519 营业总收入 归母净利润 2024 贵州茅台2024年度业绩 归母净利润及各自同比增速 以及茅台酒与系列酒的收入结构 分产品收入 年报 | 贵州茅台 2024 年年报 茅台酒 系列酒 收入结构 亿元 |
| Q01-3 | 贵州茅台 600519 营业总收入 归母净利润 2024 贵州茅台2024年度业绩 归母净利润及各自同比增速 以及茅台酒与系列酒的收入结构 年度报告摘要 公司公告 | 贵州茅台 2024 年年度报告摘要 巨潮资讯 600519 营业总收入 |
| Q04-1 | 宁德时代 300750 营业收入 归母净利润 2024 宁德时代2024年度业绩 营业收入与归母净利润各自同比方向与幅度 并 营收下降而利润增长的成因 年度报告 | 宁德时代 2024 年年度报告 营业收入 归母净利润 各自同比 |
| Q04-2 | 宁德时代 300750 营业收入 归母净利润 2024 宁德时代2024年度业绩 营业收入与归母净利润各自同比方向与幅度 并 营收下降而利润增长的成因 原材料价格 毛利率 业绩说明 | 宁德时代 2024 年营收下降利润增长 原材料价格 毛利率 成因 |
| Q04-3 | 宁德时代 300750 营业收入 归母净利润 2024 宁德时代2024年度业绩 营业收入与归母净利润各自同比方向与幅度 并 营收下降而利润增长的成因 年度报告 公司公告 | 宁德时代 2024 年年度报告 巨潮资讯 300750 营业收入 毛利率 |
| Q16-1 | 宁德时代 公司 比亚迪 公司 2024年宁德时代与比亚迪全球动力电池装机量 市场份额与排名 SNE Research 年度统计 | 2024 年全球动力电池装机量 宁德时代 比亚迪 市场份额 SNE Research |
| Q16-2 | 宁德时代 公司 比亚迪 公司 2024年宁德时代与比亚迪全球动力电池装机量 市场份额与排名 中国汽车动力电池产业创新联盟 年度数据 | 2024 年中国动力电池装车量 宁德时代 比亚迪 市占率 行业协会 |
| Q16-3 | 宁德时代 公司 比亚迪 公司 2024年宁德时代与比亚迪全球动力电池装机量 市场份额与排名 装机量 市占率 第一 第二 | 宁德时代 比亚迪 2024 年全球动力电池市占率 第一 第二 |
| Q19-1 | 2024至2025年中国创新药License-out出海交易规模 代表交易 潜在总金额与首付款 行业统计 年度报告 | 2024 至 2025 年中国创新药 License-out 交易总额 首付款 公司公告 |
| Q19-2 | 2024至2025年中国创新药License-out出海交易规模 代表交易 潜在总金额与首付款 恒瑞医药 公司公告 GLP-1 | 2024 年恒瑞医药 GLP-1 海外授权 首付款 潜在总金额 公告 |
| Q19-3 | 2024至2025年中国创新药License-out出海交易规模 代表交易 潜在总金额与首付款 代表交易 公司公告 | 2025 年中国创新药 License-out 代表性交易 首付款 总金额 公司公告 |
| Q26-1 | 宁德时代 300750 宁德时代匈牙利工厂截至2025年底的项目公告 开工 建设进展 规划产能与已建成产能 2022 项目公告 | 宁德时代 匈牙利工厂 2022 年公告 100GWh 开工 建设进展 |
| Q26-2 | 宁德时代 300750 宁德时代匈牙利工厂截至2025年底的项目公告 开工 建设进展 规划产能与已建成产能 2024 2025 建设进展 公司披露 | 宁德时代 匈牙利工厂 2024 至 2025 年建设进展 投产 已建成产能 |
| Q26-3 | 宁德时代 300750 宁德时代匈牙利工厂截至2025年底的项目公告 开工 建设进展 规划产能与已建成产能 官方 投产 产能 | CATL Hungary Debrecen factory official construction progress 2025 capacity |
| Q28-1 | 2024年光伏行业减产挺价与行业自律事件线 协会倡议 重点会议 企业行动与实际执行 中国光伏行业协会 倡议 | 2024 年光伏行业 自律 减产挺价 中国光伏行业协会 会议 倡议 |
| Q28-2 | 2024年光伏行业减产挺价与行业自律事件线 协会倡议 重点会议 企业行动与实际执行 反内卷 座谈会 | 2024 年光伏行业 防止内卷式恶性竞争 座谈会 企业减产行动 |
| Q28-3 | 2024年光伏行业减产挺价与行业自律事件线 协会倡议 重点会议 企业行动与实际执行 企业公告 减产执行 | 2024 年光伏企业 自律会议 控制产能 价格治理 实际执行 |

机械守卫证明这些查询不含原始整句（含原标点）、问号、“有哪些/是什么/为何/如何”、内部审计串，且已知实体带 symbol 或“公司”。人工判读仍显示部分主题 facet 偏长；C7 结果不支持声称查询质量已经达到人工基准，只能确认结构和消歧守卫成立。由于 C7 已使用已提交生成器完成冻结测量，测量后没有再修改生成器。

## C6：详细分析关联性

`docs/decisions/019-a/deliverable_checklist.md` 已收紧为：详细分析必须与关键发现共享 `entity + normalized_metric`，或显式复用关键发现脚注；否则只能进入独立“补充事实”节。LLM 报告渲染在 `src/deepresearch_agent/agents/reporter.py:300-422` 维护关键事实键与 Evidence ID，不能追溯的 claim 转入补充事实。

### 修复前完整两节

```markdown
## 关键发现
- 宁德时代2024年12月31日累计营业收入为3620.13亿元。 [^3]
- 宁德时代2024年12月31日累计归母净利润为507.4468亿元。 [^5]

## 详细分析
### 宁德时代 2024 年业绩、欧洲工厂扩张与风险有哪些可核验事实？
- 欧洲工厂投产日期仍是预测性披露，应以最新官方建设进展核验。 [^2]
```

### 修复后完整两节

```markdown
## 关键发现
- 宁德时代2024年12月31日累计营业收入为3620.13亿元。 [^3]
- 宁德时代2024年12月31日累计归母净利润为507.4468亿元。 [^5]

## 详细分析
### 宁德时代 2024 年业绩、欧洲工厂扩张与风险有哪些可核验事实？
- 营业收入规模是评估扩张承受力的财务基线；工厂投产日期仍需以最新官方进展核验。 [^3] [^2]
```

修复后详细项显式复用关键发现脚注 `[^3]`，不可追溯项数为 `0`；它同时保留投产风险脚注 `[^2]`，未删证据。

## C7：APBEC

指标定义见 `primary_evidence_closure.md`，结果见 `primary_evidence_closure_result.md`。

- 指标 commit：`364b283 2026-07-25T11:35:05+01:00`；
- 测量脚本 commit：`058e824 2026-07-25T11:38:04+01:00`；
- 时间顺序成立；
- 查询 `18/18`，抓取 `18/30`，LLM `0`；
- Q01 `0/3`、Q04 `0/3`、Q16 `0/2`、Q19 `0/4`、Q26 `0/3`、Q28 `0/3`；
- 宏平均 `0`，达 `2/3` 题数 `0/6`，冻结阈值失败。

019-B 测的是固定人工查询的 Tavily top-5 可达性；APBEC 测的是 Agent 自生成查询到实际抓取一手正文的闭合。前者仍为 `REACHABLE=2 < 4` STOP，后者进入分支 F；两项并列，不互相覆盖。

## C8：零网络全图复验

运行条件为 `DEEPRESEARCH_MODE=llm`、11 个超集开关全开、手写 stub completion。原始输出：

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

四类产物齐全：reader report、structured output、audit bundle、research snapshot；trajectory 另行存在。C1–C6 定向守卫 `Ran 14 tests ... OK`。公开 checklist 的机械项为：缺节 0、无引用结论 0、科学计数 0、raw period key 0、重复营收事实 0、两节不相等且详细分析关联项 0、结构化完整、引用闭合 ok。

## 新增/调整守卫及“移除改动”验证方式

| 测试 | 防止的回归 | 移除本阶段改动时的失败方式 |
| --- | --- | --- |
| `test_sufficiency_score_is_sensitive_before_components_saturate` | 因变量在未饱和 Evidence/域变化时被锁死 | 将 Evidence/域分量常量化，`0.833333 != 1.0` |
| `test_complete_growth_relationship_triggers_a_numeric_check` | 完整增长关系仍 `checks=0` | 禁用增长匹配/查找，`check_count != 1` |
| `test_financial_and_event_verification_select_fetch_with_reason` | financial/event 再次拒绝 fetch 或 criterion 为空 | 回退旧 rule，selected 不含 `web_fetch` |
| `test_selected_fetch_hydrates_results_and_consumes_branch_budget` | 只记录选择却不读取正文，或 fetch 不计预算 | 移除 Researcher fetch 接线，缺少 fetch event/预算计数 |
| `test_fetch_hydrates_publisher_html_body` | provider 只有 search 没有正文 fetch | 移除 `TavilySearchProvider.fetch`，调用失败 |
| `test_query_uses_entity_identifier_facets_not_question_prose` | 回到整句问法或丢失 symbol/metric/period/doc type | 回退旧拼接器，命中问句/缺 300750 |
| `test_company_name_without_symbol_gets_company_disambiguator` | 无代码实体无消歧 | 移除“公司”fallback，断言失败 |
| `test_llm_reader_render_normalizes_and_deduplicates_facts` 新增关联断言 | 详细分析和关键发现无关系 | 回退关联分流，详细项不共享 `[^3]` |
| `test_expanded_016_configuration_is_complete_and_strictly_replays` 调整 | fetch 新增后轨迹预算事实未进入严格回放 | 不更新真实 tool trace 计数，strict replay 不一致 |

上表给出可复现的 mutation 方法；本轮没有为展示 mutation 而改写当前工作树。所有原断言保留。仅两处既有断言按新增真实 tool 行为更新：研究预算从只数 search 改为数 search+fetch；严格轨迹增加 fetch tool call。这是契约范围扩展，不是降低阈值。

## 测试文件修改理由

- `test_research_loop.py`：增加 C1 灵敏度守卫。
- `test_numeric_consistency.py`：增加 C3 最小触发守卫。
- `test_dynamic_capability.py`：增加 C4 financial/event fetch、criterion、DecisionGate 守卫；原 narrative 负例保留。
- `test_researcher_search_budget.py`：增加实际 fetch 与预算扣减守卫。
- `test_tavily_search.py`：增加 HTML 正文 fetch、重试边界和规范化守卫。
- `test_replan_query_guard.py`：增加 C5 问句禁用、实体消歧、字段组成守卫；180 字符和禁词未放宽。
- `test_report_reader_guard.py`：增加 C6 关键发现—详细分析关联与补充事实分流守卫。
- `test_expanded_trajectory.py`：把新增 fetch 调用纳入严格轨迹计数，没有弱化 replay。

没有删除、skip 或 xfail 测试，没有修改 Golden。

## 生产代码规模

以 `git diff --numstat main -- src` 计：

- 新增 244 行；
- 删除 34 行；
- 总 churn `244 + 34 = 278` 行；
- 距 320 行上界剩余 `42` 行。

测量脚本和测试不计入生产 `src/` 上界。没有逼近或越过分支 H。

## 遗留与风险

1. APBEC 为 0：Q01/Q26 已到公司 PDF，但 fetch 只处理 HTML；PDF 正文解析/直连仍缺失。
2. Q04/Q16/Q19/Q28 的 top-1 抓取仍停在二手来源；当前 Researcher 只 fetch 每次搜索的返回项（本次测量 top-1），没有一手域名 rerank。
3. C5 查询虽然通过结构、消歧和禁词守卫，人工对照仍显冗长；没有证据证明它达到人工查询质量。
4. C1 因变量平台区未修复；修改指标会改变实验语义，必须由 PM 重新预登记。
5. C2 深度 3 的“足够”是本卡机械阈值与 fixture 证据，不代表真实 LLM 判断质量；成本倍率也仅是 stub 比例。
6. Q28 是否存在能同时证明协会倡议和企业实际执行的干净一手答案尚无证据。
7. Tavily fetch 的 HTML 去标签是轻量实现，不是通用文档解析器。

## 对 019-D 的影响

事实与建议详见 `impact_on_019d.md`。结论是 019-D 不应付费启动：019-B 可达性 STOP 未解除，C1 因变量平台区、C2 输入深度不足、C7 APBEC=0 又分别构成更早的实验有效性阻断。建议 PM 先选择因变量重设计、反思深度以及一手 PDF/rerank 路径，再决定是否重写预登记；本卡没有自行修改任何上限或实验参数。

## 诚实声明

机械验证：

- 公式、实际分量、灵敏度输入输出；
- 三档深度信号计数、字符数与 tool call；
- 四个数值观测及 `checks=0`，最小场景 `checks=1`；
- AgentDecision 前后 JSON、DecisionGate、预算和 tool trace；
- 18 条离线查询、18 次 Tavily/18 次 fetch、APBEC 六题为 0；
- C8 产物、引用闭合、契约和守卫输出；
- 生产代码 278 行 churn。

人工判读：

- “至少 3/4 类非零信号”为有意义反思的最低信息量；
- C5 输出仍偏冗长；
- Q01/Q26 主因归为 PDF 解析边界，其余题主因归为排名/一手直达；
- 因变量改造范围 80–140 行。

尚无证据支持：

- 深度 3 会让真实 LLM 产生更优策略；
- C5 查询优于 019-B 人工查询；
- 加入 PDF 解析或 rerank 后 APBEC 一定达标；
- Q28 一定存在干净一手闭环；
- 任一付费模型能改善充分性或证据质量。

## 自检

- 是否因结果不理想调整标准：**否**。APBEC 定义/分母/阈值在 `364b283` 冻结，测量脚本在其后提交；测量后未修改。019-B 判据和 STOP 未改。
- 是否为“有产出”制造诊断修改：**否**。C1 未改指标语义；C2 未改深度与输入边界；C3 判定为正确行为，只加触发守卫。
- 是否放宽既有阈值或断言：**否**。查询 180 字符/禁词与 checklist 均未放宽；报告关联判据只收紧。
- 是否调用 LLM 或超网络预算：**否**。LLM 0；C7 查询 18、fetch 18；其他阶段零网络。
- 是否触碰冻结资产或默认 content-affecting 开关：**否**。

## 提交前 Git 原始证据

以下输出在最终文档提交前采集；最终提交后的最新原始输出另写入 ignored 协作报告。

`git log --oneline main..HEAD`

```text
058e824 feat: add zero-cost primary evidence probe
364b283 docs: freeze primary evidence closure metric
084740a fix: close first-party evidence retrieval loop
0115a99 test: guard research instrument sensitivity
```

`git diff main --stat`

```text
 docs/decisions/019-a/deliverable_checklist.md      |   2 +-
 docs/decisions/019-c/acceptance.md                 |  91 ++++
 docs/decisions/019-c/impact_on_019d.md             |  43 ++
 docs/decisions/019-c/primary_evidence_closure.md   |  66 +++
 .../019-c/primary_evidence_closure_result.md       |  82 ++++
 docs/decisions/019-c/report.md                     | 510 +++++++++++++++++++++
 scripts/measure_primary_evidence_closure.py        | 343 ++++++++++++++
 src/deepresearch_agent/agents/reporter.py          |  56 ++-
 src/deepresearch_agent/agents/researcher.py        |  12 +
 .../orchestration/research_loop.py                 |  70 ++-
 src/deepresearch_agent/settings.py                 |   6 +-
 .../tools/capability_registry.py                   |   6 +-
 .../tools/capability_selector.py                   |  26 +-
 src/deepresearch_agent/tools/tavily_search.py      |  65 +++
 src/deepresearch_agent/workflow/engine.py          |  37 +-
 tests/integration/test_expanded_trajectory.py      |   1 +
 tests/unit/test_dynamic_capability.py              |  45 +-
 tests/unit/test_numeric_consistency.py             |  32 ++
 tests/unit/test_replan_query_guard.py              |  55 +++
 tests/unit/test_report_reader_guard.py             |  28 +-
 tests/unit/test_research_loop.py                   |  28 ++
 tests/unit/test_researcher_search_budget.py        |  41 ++
 tests/unit/test_tavily_search.py                   |  51 ++-
 23 files changed, 1657 insertions(+), 39 deletions(-)
```

## 最终提交后 Git 原始证据

`git status --short`

```text
（无输出，工作树 clean）
```

`git log --oneline main..HEAD` 与 `git diff main --stat` 的连续原始输出：

```text
479d135 docs: record 019-c viability decision
058e824 feat: add zero-cost primary evidence probe
364b283 docs: freeze primary evidence closure metric
084740a fix: close first-party evidence retrieval loop
0115a99 test: guard research instrument sensitivity
 docs/decisions/019-a/deliverable_checklist.md      |   2 +-
 docs/decisions/019-c/acceptance.md                 |  91 ++++
 docs/decisions/019-c/impact_on_019d.md             |  43 ++
 docs/decisions/019-c/primary_evidence_closure.md   |  66 ++++
 .../019-c/primary_evidence_closure_result.md       |  82 ++++
 docs/decisions/019-c/report.md                     | 533 +++++++++++++++++++++
 scripts/measure_primary_evidence_closure.py        | 343 ++++++++++++++
 src/deepresearch_agent/agents/reporter.py          |  56 ++-
 src/deepresearch_agent/agents/researcher.py        |  12 +
 .../orchestration/research_loop.py                 |  70 ++-
 src/deepresearch_agent/settings.py                 |   6 +-
 .../tools/capability_registry.py                   |   6 +-
 .../tools/capability_selector.py                   |  26 +-
 src/deepresearch_agent/tools/tavily_search.py      |  65 +++
 src/deepresearch_agent/workflow/engine.py          |  37 +-
 tests/integration/test_expanded_trajectory.py      |   1 +
 tests/unit/test_dynamic_capability.py              |  45 +-
 tests/unit/test_numeric_consistency.py             |  32 ++
 tests/unit/test_replan_query_guard.py              |  55 +++
 tests/unit/test_report_reader_guard.py             |  28 +-
 tests/unit/test_research_loop.py                   |  28 ++
 tests/unit/test_researcher_search_budget.py        |  41 +-
 tests/unit/test_tavily_search.py                   |  51 +-
 23 files changed, 1680 insertions(+), 39 deletions(-)
```

## 最终提交前闸门原始摘要

```text
Ran 357 tests in 15.951s

OK
ruff 0.15.15
All checks passed!
frozen_asset_diff=empty
c9_documents=present
```

测试命令使用 deterministic fixture 与 ignored SQLite 路径；没有调用 LLM provider。C7 的唯一网络批次为 Tavily 18 次、HTTP fetch 18 次。
