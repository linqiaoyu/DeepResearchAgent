# 033 LLM 模式语义评价链路

## null 的成因

根因是运行链路从未接通，不是 judge 输出被丢弃。旧 `EvaluatorAgent` 在 LLM 模式直接把
`citation_accuracy`、`answer_relevance`、`faithfulness` 设为 `None`；Golden round 的
多样本 judge 位于另一条离线脚本链路，Engine 从未构造或调用它。因此旧的
`task_success=1` 只证明“报告和 Evidence 存在且机械 numeric mismatch 为零”，不能解释为
完整、相关或忠实。

## 本轮决策

新增默认关闭的 `RuntimeSemanticJudge`，通过统一 `LLMClient` 的 `judge` role 调用严格
Pydantic schema。它只评估：

- answer completeness：是否覆盖问题要求；
- answer relevance：是否围绕问题；
- answer shape：是否形成可读且真正回答问题的研究报告；
- citation support：引用 Evidence 是否语义支持对应结论；
- faithfulness：全文是否受提供 Evidence 约束。

精确数字、方向、小数点、量级和 citation identity 仍由机械审计决定。Judge 的满分不能
覆盖 numeric mismatch；机械错误会继续把 `task_success` 置为 0，并把最终
`citation_accuracy` 上限压到机械 citation resolution，数值错时强制为 0。

## 失败与可复现边界

- `SEMANTIC_JUDGE_ENABLED=false`、启用但无 client、以及 judge 调用失败分别留下不同的
  typed null reason；不能把失败伪装成 0 分或估算分。
- 付费预算异常仍走 run-level terminal，不能被“可选指标失败”吞掉。
- Judge prompt、typed response 与 usage 进入同一 trajectory FIFO；strict replay 缺 judge
  调用时明确 cache miss。
- 输入先保留 `report_footnote_evidence` 映射所指 Evidence，再受 80 条与约 12k token 双
  上限；payload 明示 total/included/omitted、估算 token 及被省略的映射 Evidence ID。
- 对报告中的实验 arm、Reflector 和决策记录文字做盲化，避免 judge 从组名猜测优劣。

## 合同变更

`EvaluationResult` 新增 `answer_completeness`、`answer_shape` 及各维 reason；LLM 模式的
`citation_accuracy` / `answer_relevance` / `faithfulness` 在启用 judge 且成功时不再是
`null`。这是一项新增/加严评价合同，已同步 `docs/evaluation.md`、prompt registry、manifest
flag 分类与配置校验。默认仍关闭，离线 CI 不需要 API key。

最终真实 Flash/Pro 两个 arm 固定使用同一个 Qwen judge；其真实分数和成本在本轮结果记录
中并列发布。数字质量结论不引用 judge 分数。
