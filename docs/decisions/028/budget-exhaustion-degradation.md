# 028: 外部请求预算耗尽的降级产出

## 决策

当外部 search/fetch 运行级预算拒绝请求时，保留 `budget_exceeded` 状态、预算快照和
`external_request_budget_rejected` 决策，同时调用 Reporter 生成非空报告，并追加明确的
“数据缺失与资源耗尽”限制及原始拒绝原因。

## 证据与边界

027 的真实 Tavily 运行在 20/20 fetch 预算处返回零字节报告；已有 chaos 场景已经规定
局部失败必须标记后继续。本改动只覆盖运行级预算拒绝的终端分支；它不调高默认预算，
不改变 selector、检索顺序或冻结基线。

## 验证与回滚

`test_engine_records_budget_refusal_as_a_gated_decision` 断言状态、预算快照、非空报告、
缺失标记与耗尽原因均保留。删除报告中的缺失标记会使该测试失败。回滚方式是在新的提交中
移除该报告降级段和相应断言；不得将预算拒绝伪装成成功。

## 未决事实

本轮真实运行确认：LLM planner 的金融子问题没有得到原始题目的证券身份补全，且当前
`Settings.dynamic_capability_rules_json` 的 financial_metric 默认列表也不含
`disclosure_source`，与任务卡“已知现实”冲突。该 selector 配置/身份传播问题未在本轮
擅自修改，须在后续授权中作为同一管道修复一并处理。
