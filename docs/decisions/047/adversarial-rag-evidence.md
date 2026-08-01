# RAG 对抗候选证据边界

## 决定

`ExtractorAgent` 在 RAG `Source` 进入提取前执行最小准入检查：候选必须与子问题
存在确定性词项重合；启用注入保护时，风险分数不低于 `0.5` 的 RAG 候选被拒绝。
普通 web `Source` 的既有提取与“标记、降置信度”行为不变。

## 证据

`tests.integration.test_rag_adversarial_evidence` 串联
`RagSearchService -> ResearcherAgent -> ExtractorAgent -> CriticAgent -> ReporterAgent`，
验证无关语料、未来版本、注入文本和重复 chunk 均不能产生无支撑的最终报告结论。

Mutation M11 删除 RAG 注入准入行后，注入样本立即产生一条 `Evidence`；首次失败原始
输出保存在 `artifacts/047/mutations/b6_m11_rag_injection_admission_guard.log`。恢复该行后
四项测试与完整门禁均通过。
