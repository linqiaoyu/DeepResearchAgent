# 019-E 对 019-F 的影响

## 已证实

- `ResearchProgress` 的完整因变量重建仍有必要。最小量 `unique Evidence + independent domains + primary sources - unresolved issues` 使 Q26 从旧的第 3 轮提前停止推进到第 4 轮，并在第 4 轮同时触发 `max_iterations` 与 `no_progress_window`；它证明了最小解耦有效，但也显示预算耗尽后继续轮询不产生新信息。
- PDF 能力本身已经可用：CATL 公告在真实运行中被检索、重排为 `primary`、抓取、解码为 1965 字 Source。失败发生在 Extractor 的逐字证据合同之后，不应回退 PDF 选型。
- 当前外部预算不是全图硬熔断。BranchBudget 记录 10 个研究分支调用，但 Critic retry 另外触发大量 Tavily 查询，最终搜索账本 37 行。019-F 若继续真实实验，必须先把外部查询/抓取的 run-wide 计数放到所有搜索入口共同执行的边界。
- LLM provider 调用为 0；因此本卡没有产生金钱成本。40 次本地 stub completion 只形成零 token、零成本的类型化输出，不是 provider 调用。

## 未证实

- 本卡没有证明真实模型的研究判断质量、冲突综合能力或报告文字质量。
- 本卡没有完成 APBEC v2；不能推断六题宏平均会提升，也不能解除 019-C 的 APBEC=0。
- 本卡没有证明 E5 的 11 开关超集在本次变更后仍可生成含 primary 标注的零网络包，因为分支 C 要求停止后续。
- 本卡没有证明业务场景成立。primary Source 未进入 Evidence，关键发现仍全由 unknown/二手来源支持。

## 对 019-F 的建议

1. 保留完整 `ResearchProgress` 设计任务，不修改其预登记参数或上限；把本卡四个机械分量作为输入候选，而不是直接冻结为最终权重。
2. 在任何下一次真实网络实验前，先做零网络守卫：run-wide 外部查询熔断必须覆盖研究主路径与 Critic retry；达到上限时 fail closed，并在轨迹中记录拒绝。
3. 对 completion stub 加逐字 `extract_text in source.content` 的预飞行断言；这不是放宽 Extractor，而是让测试 harness 在触网前暴露无效 stub。
4. 下一次真实重跑需要 PM 新授权。本卡已经耗尽并超过 E3 查询预算，不能把修复后的重跑算作本卡剩余额度。
5. 019-B 的 `REACHABLE=2 < 4` 与 STOP、019-C 的冻结 APBEC 定义和阈值继续原样有效；是否进入 019-F 或付费轮由 PM 决定。

## 付费实验的证据基础

当前不成立。正面证据仅证明一手 PDF 可达、可排序、可抓取、可解码；反面证据是 primary Evidence=0、primary cited=0、E3 查询超限、APBEC v2 未运行。不能据此申请真实 LLM 支出。

