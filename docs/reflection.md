# Reflector：反思机制骨架

## 结论先行

017 实现的是反思管道，不是反思判断力。`REFLECTION_ENABLED=false` 默认关闭并归类为
`content_affecting`。开启后，Reflector 读取本次运行已记录的 `AgentTrajectory` 与全部
`AgentDecision`，产出 `ReflectionResult`；关闭时不会进入默认 manifest 载荷，两题面
characterization 保持逐字一致。

`ReflectionResult` 强制分成两条轨道：

- `deterministic_signals`：对已发生轨迹做机械、可复算的跨轮聚合；
- `llm_insight`：类型化的策略推理接口。本轮只接合成/录制占位，判断质量明确标记为
  `unverifiable_in_deterministic_mode`，真实模型接入与质量判断待 019。

因此不能把“管道能够提取信号”表述为“Agent 已具备有效反思能力”。

## 为什么必须双轨

015 的充分性度量回答“这一轮证据够不够”，属于单轮即时判据。Reflector 的确定性轨道
回答“跨轮观察到了哪些重复模式”，只提供事实基础。若把模式直接翻译为策略结论，
Reflector 仍只是另一组 if-else；它不会成为真正的推理位置。

017 因此把策略判断放进独立的 `ReflectionReasoningInterface`：

```text
ReflectionReasoningRequest
  deterministic_signals
  trajectory_summary
        |
        v
ReflectionReasoningInterface
        |
        v
ReflectionLLMInsight
  status / insights / cache_key / quality_validation
```

这是认知路线中第一个明确为真实 LLM 决策预留的位置：先前循环停止、预算、分类与重规划
都由确定性规则完成；此接口未来接收机械事实并产出需要人工评价的策略洞察。接口存在不
等于判断已经发生。

本轮 `SyntheticFixtureReflectionReasoner` 只证明 schema、调用、轨迹和路由接通，token
固定为 0。`RecordedReflectionReasoner` 只接受精确 cache key；未见信号组合返回
`cache_miss`、`must_stop=true`，工作流暂停并报告，不编造洞察。

## 四类确定性信号

四类信号都来自可定位的轨迹片段，并形成
`reflection_signal_extraction` `AgentDecision`：

1. 持续薄弱子问题：至少两个重规划轮次中始终存在充分性 gap 的子问题；
2. 反复无效来源：在至少两次独立搜索调用中出现、但未进入已采纳 Evidence 域名集合的
   来源域名；同一次搜索返回同域多页只计一次；
3. 重复 Critic issue：跨 Critic 节点至少出现两次的 issue 类型及计数；
4. 无效重规划轮次：存在重规划决定，但下一轮充分性进展没有提高的轮次。

这些阈值是机械聚合口径，不是“应采用什么策略”的判断。相同轨迹与决定会得到相同信号。

## 重规划与记忆接线

当 `REFLECTION_ENABLED=true` 且研究循环实际开启时，只有
`deterministic_signals` 进入只读 `DecisionContext`。现有
`refine_research_plan` 可据此为持续薄弱项生成定向恢复意图、避开反复无效域名、处理重复
issue，或在无进展后换取证角度；循环仍复用原有 `BoundedLoop` 和 LangGraph 条件回边。

`llm_insight` 不在 `DecisionContext` 中，本轮不能改变重规划。报告“研究过程”会列出
信号、调整后的下一轮查询，并明确说明 LLM 洞察未参与。

同一节点还把“问题类型—检索策略—充分性结果—反思信号”写入
`ProceduralMemory`。写入形成 `procedural_memory_write` `AgentDecision`，轨迹使用 016
预留的 `memory_writes` 槽位。读取历史不会自动选择未来策略。

## 019 接入与评判标准

019 只有在完成支出预登记后，才可用真实 `LLMClient` 适配
`ReflectionReasoningInterface`。建议超集配置在 016 配置基础上额外开启：

```text
TRAJECTORY_RECORD_ENABLED=true
RESEARCH_LOOP_ENABLED=true
DEEPRESEARCH_RESEARCH_LOOP_MAX_ITERATIONS=2
DECISION_WEAVING_ENABLED=true
NUMERIC_CHECK_ENABLED=true
DYNAMIC_CAPABILITY_ENABLED=true
REFLECTION_ENABLED=true
```

真实模型输出必须保持 `StrategyInsight` schema，至少说明目标、建议与依据；人工评判应
检查建议是否由输入信号支持、是否比无反思对照产生更具体且不重复的检索意图、是否改善
引用闭合或关键 gap、是否引入无依据来源偏见，以及新增 token、费用和延迟是否在预登记
阈值内。每项点亮必须有回滚条件。

## 明确不做什么

- 不声明合成占位洞察有质量；
- 不让 `llm_insight` 自动改变行为；
- 不用程序性记忆自动排序或选择策略；
- 不实现记忆遗忘、压缩或跨进程持久化；
- 不调用真实 provider、judge 或付费 API；
- 不把 fixture 的接线正确性解释为真实研究改善。
