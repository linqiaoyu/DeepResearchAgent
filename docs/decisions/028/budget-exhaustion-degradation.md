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

## 030 勘误：预算口径与后续修复

028 的“实际 fetch egress”表述不完整：运行预算按 HTTP 请求种类计数，而非按上层
`web_fetch` 调用次数计数。CNINFO disclosure 一次成功调用会消耗两次 `fetch`（证券
身份查询与 PDF 下载）和一次 `search`（公告查询）；Tavily 的网页抓取也消耗 `fetch`。
因此“6 search + 14 fetch”不能推导出 fetch 预算仍有六次余量，且网页抓取与 disclosure
共用 fetch 额度，可能在权威披露调用前将其耗尽。

030 随后修复了两项当时未决事实：LLM planner 对显式、已识别的 A 股财务问题会保留证券
身份，且 financial_metric 默认规则包含 `disclosure_source`。另发现并修复默认 LLM
engine 虽注册 CNINFO source 但未将其注入 Researcher 的管道断点。预算隔离尚未实施；
预计需扩展 `ExternalRequestBudget` 为按工具或请求类单列额度，并为 disclosure 预留额度，
属于会改变运行经济学的后续工作。
