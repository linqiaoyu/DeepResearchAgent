# 019-B 验收卡

阶段：B0
状态：COMPLETE
验收命令：全量 unittest；`ruff --version`；Ruff、prompt drift、characterization、chaos、site build
通过判据：基线 347 tests/0 failures；Ruff 精确 0.15.15；其余闸门全绿
失败含义：分支起点不可信，后续差异无法归因
原始输出：`b0_full_tests.txt`、`b0_ruff_version.txt`、`b0_ruff.txt`、`b0_prompt_drift.txt`、`b0_characterization.txt`、`b0_chaos.txt`、`b0_build_site.txt`

阶段：B1
状态：COMPLETE
验收命令：`rg`/`sed` 机械检查 Reporter、ReportDraft 与 research loop 构造路径
通过判据：六个一级章节、两节数据来源、数字路径和重规划拼接点均定位到函数与行号
失败含义：无法证明修复发生在正确生成层
原始输出：`report.md` 的 B1 表与代码定位

阶段：B2
状态：COMPLETE（预登记 Branch B）
验收命令：`run_b2_probe.py`；`render_b2_reachability.py`
通过判据：Tavily basic 请求恰为 18；六题全部人工判定；无 LLM 调用；金钱成本 ¥0
失败含义：检索层可达性未知，019-C 负面结论无法归因
原始输出：`b2_probe_output.txt`、`b2_search_ledger.jsonl`、`retrieval_reachability.md`

阶段：B3
状态：COMPLETE
验收命令：`python -m unittest tests.unit.test_replan_query_guard -v` 与 B6 决策链检查
通过判据：禁词命中 0；长度不超过 180；issue id/type/message 留在 AgentDecision
失败含义：确定性候选查询仍被内部诊断污染，双臂对照不公平
原始输出：`precommit1b_full_tests.txt`、`b6_output_retry1.txt`、`guard_mutation_output.txt`

阶段：B4
状态：COMPLETE
验收命令：`python -m unittest tests.unit.test_report_reader_guard -v` 与 B6 报告机械检查
通过判据：科学计数法 0、原始期间键 0、重复收入事实 0、两节结论集合不相同
失败含义：读者报告仍违反已冻结的 019-C 否决门槛
原始输出：`precommit2_full_tests.txt`、`b6_output_retry1.txt`、`guard_mutation_output.txt`

阶段：B5
状态：COMPLETE
验收命令：全仓 `rg` 策略回放相关词与 `tests.integration.test_trajectory_replay`
通过判据：strategy mode 被明确拒绝；所有剩余文字均说明未实现或历史缺口
失败含义：代码行为与对外能力表述仍不一致
原始输出：`precommit3_full_tests.txt`、`precommit4_full_tests.txt`、`guard_mutation_output.txt`

阶段：B6
状态：COMPLETE
验收命令：`run_b6_zero_network.py` 与 jq/文件存在性复核
通过判据：network_calls=0；11 开关全开；产物齐；引用闭合 ok；blocked=0；契约通过
失败含义：B3/B4 只能由孤立单测证明，不能证明全图兼容
原始输出：`b6_output_retry1.txt`、`b6_artifact_validation.txt`、`b6_stub_package/`

阶段：B7
状态：COMPLETE（Branch B STOP）
验收命令：最终全套绿灯、冻结路径 diff、生产代码行数、git log/stat 审计
通过判据：350 tests/0 failures；Ruff 0.15.15；受限文件 0 变更；215/350 行；报告三件套齐
失败含义：不能把本轮提交为可审查的零成本结论
原始输出：`final_*`、`precommit4_*`、`report.md`、`acceptance.md`、`impact_on_019c.md`
