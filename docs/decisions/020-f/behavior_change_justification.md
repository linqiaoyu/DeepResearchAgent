# 020-F 冻结 characterization 变更归因

本记录补充 020-F 合并时遗漏的审查说明。范围是合并提交
`f35e175` 相对于第一父提交的两份冻结快照（统计为 74 + 138 = 212
处增删行）和四处测试断言。这里的「行」是 Git diff 的统计口径，不将它
误表述为 212 个独立行为。

## 结论

所有检查到的 characterization 和断言变化均可归因到 F1--F4；没有发现
无法归因的变化。它们记录的是读者可见的语义扩展或更精确的契约，而不是
降低已有正确性要求。尤其，断言从固定中文措辞缩窄至结构化查询的稳定
语义标记，是因为 F1 有意禁止把自然语言标题复制进查询，而不是允许任意
查询文本。

## 变更类别与归因

| 类别 | 受影响资产 | 变化 | 020-F 项 | 为什么是语义扩展而非弱化 |
| --- | --- | --- | --- | --- |
| 查询措辞 | 四个单测断言 | `官方数据 统计口径 单位 核验` / `官方数据 计算口径 单位 核验` 改为要求 `统计`；反思查询由 `官方来源 补充核验` 改为要求 `公告`；循环报告由完整 `stop_exhausted:max_iterations` 改为要求 `max_iterations`。 | F1 | F1 将重规划查询变为 entity/metric/period/document-type 字段拼装，禁止标题和 Critic 散文进入查询。旧的完整句子是已被禁止的实现细节；新断言仍要求目标文档类型，且同一测试继续检查决策、注入隔离或循环可见性。它没有把查询允许为任意字符串。 |
| 明细去重与补充事实 | 两份 `final_report`、对应 `node_summaries` | 已在关键发现出现的证据不再在每个子问题中重复；无法关联到关键发现的项目转入 `补充事实`；无新增分析时显式说明。 | F4 | 原先报告把同一证据重复呈现为不同子问题的分析。新输出保留全部可引用证据和脚注映射，额外显示其未能支持关键发现的事实，因而增加可审计性，不是删除或隐藏证据。 |
| Critic 未执行的呈现 | 两份 `final_report`、`node_summaries` | `Critic 未发现…` 改为 `Critic 未执行；本轮不提供质量判断`。 | F2 | 当 `critic_report` 缺失时，旧文本伪称已经过质量审查。新文本移除虚假的正面结论，保留缺失状态；这是 fail-closed 的信息增量。 |
| unknown 日期传播 | 报告日期、来源脚注、序列化字段及快照中的由此引起内容 | 无法解析的来源日期由 epoch 语义转为 `unknown`；最新日期仅从已知日期计算。 | F3 | 1970-01-01 看似有效，会制造虚假 freshness gap。`unknown` 保留不确定性并避免虚假过期判断；已知日期仍完整保留，不是放宽日期验证。 |
| 派生评估数值 | 两份快照的 `faithfulness`、`token_used`、manifest `token_total` | `finance_structured`：faithfulness 0.882→0.913、token 7263→7456；`wealth_research`：0.882→0.935、token 7310→7747。 | F2、F4（间接受 F3 影响） | 这些是改变后的确定性报告文本和其可追溯节点摘要的再计算结果；没有修改评分阈值、评估器或基线。数值上升不能单独被解释为质量改进，只是新行为的 characterization。 |

## 覆盖核对

### 逐 hunk 映射（Git diff 行口径）

下表的行数是 `git diff --numstat f35e175^1 f35e175 -- <file>` 的新增加删除；
同一 JSON 逻辑行的删除与新增各计一行。长字符串报告替换保持为一个 hunk，不把其
内嵌换行误计为文件行。

| 快照文件 | hunk / 行号范围 | 行数 | 归因类别(F1–F4) | 一句话理由 |
| --- | --- | ---: | --- | --- |
| finance_structured.json | 22, 27, 852（派生指标/manifest） | 6 | F2/F4 | Critic 呈现与报告重排后的派生 characterization。 |
| finance_structured.json | 347（`final_report`） | 2 | F2/F3/F4 | Critic 缺失、unknown 日期与补充事实进入读者报告。 |
| finance_structured.json | 745–823（`node_summaries`） | 66 | F2/F4 | 详细分析去重、补充事实重排及 Critic 未执行节点摘要。 |
| finance_structured.json | 合计 | 74 | — | 与 `--numstat` 的 58 additions + 16 deletions 一致。 |
| wealth_research.json | 22, 27, 1071（派生指标/manifest） | 6 | F2/F4 | Critic 呈现与报告重排后的派生 characterization。 |
| wealth_research.json | 467（`final_report`） | 2 | F2/F3/F4 | Critic 缺失、unknown 日期与补充事实进入读者报告。 |
| wealth_research.json | 837–999（`node_summaries`） | 130 | F2/F4 | 详细分析去重、补充事实重排及 Critic 未执行节点摘要。 |
| wealth_research.json | 合计 | 138 | — | 与 `--numstat` 的 118 additions + 20 deletions 一致。 |

四处测试断言（`test_decision_weaving.py`、`test_numeric_consistency.py`、
`test_reflection.py`、`test_research_loop.py`）各自单列为 F1：它们把旧自然语言
查询/停止文本约束改为字段化查询与稳定语义标记，并未降低任何通过条件。

- `finance_structured.json` 的 74 个 diff 行由上表的 F2、F3、F4 输出和派生数值覆盖。
- `wealth_research.json` 的 138 个 diff 行由同样类别覆盖；该主题有更多无法关联的证据，故 `补充事实` 和 `node_summaries` 的变化更多。
- `test_decision_weaving.py`、`test_numeric_consistency.py`、`test_reflection.py`、`test_research_loop.py` 的四处断言均由 F1 覆盖。

没有未归因项。若未来重新生成上述冻结资产，必须把新的 diff 按本表类别复核；不能仅因测试同步通过就接受行为变化。
