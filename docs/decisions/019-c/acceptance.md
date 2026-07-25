# 019-C 验收卡

## C0

- 阶段：C0 分支与基线
- 状态：COMPLETE
- 验收命令：`git branch --show-current`; `.venv/bin/python -m unittest discover -s tests`; `.venv/bin/python -m ruff --version`; `.venv/bin/python -m ruff check src tests scripts`; `test -d docs/decisions/019-a -a -d docs/decisions/019-b`
- 通过判据(具体字符串或数字)：分支=`task/019c-instrument-viability`；tests>=350、failures=0；`ruff 0.15.15`；019-A/B 均存在
- 失败含义：基线或公开前置记录不成立，必须 STOP 交 PM
- 原始输出：`Ran 350 tests in 15.812s`；`OK`；`ruff 0.15.15`；`All checks passed!`

## C1

- 阶段：C1 充分性指标灵敏度诊断
- 状态：COMPLETE（判定进入分支 B）
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_research_loop.ResearchSufficiencyTest.test_sufficiency_score_is_sensitive_before_components_saturate -v`
- 通过判据(具体字符串或数字)：守卫 `ok`；stub 两轮逐分量均=`[1,1,1,1,0,1]`、score=`0.833333`；灵敏度场景至少一处 delta!=0
- 失败含义：不知道因变量是否可动，付费实验无法归因
- 原始输出：`test_sufficiency_score_is_sensitive_before_components_saturate ... ok`；构造表 score=`0.166667,0.583333,0.666667,0.750000,0.833333,1.000000,0.833333,0.833333`

## C2

- 阶段：C2 反思器输入信息量诊断
- 状态：COMPLETE（判定进入分支 C）
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python _collab/019c_instrument_viability/run_c2_depths.py`
- 通过判据(具体字符串或数字)：深度 2/3/4 均有完整请求；信号计数与字符数可机械复算；不得调用网络/LLM
- 失败含义：无法知道真实 reasoner 输入或深度影响
- 原始输出：depth2=`0/0/1/1, 2 nonzero, 816 chars, 9 calls`；depth3=`1/0/1/2, 3 nonzero, 961 chars, 14 calls`；depth4 实际 3 轮且与 depth3 相同

## C3

- 阶段：C3 数值自洽校验空转诊断
- 状态：COMPLETE（判定为 (a) 正确行为）
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_numeric_consistency.NumericConsistencyTest.test_complete_growth_relationship_triggers_a_numeric_check -v`
- 通过判据(具体字符串或数字)：实际四观测无匹配关系、`check_count=0`；最小完整增长关系 `check_count=1` 且守卫 `ok`
- 失败含义：校验器可能在应触发时仍空转
- 原始输出：`test_complete_growth_relationship_triggers_a_numeric_check ... ok`；实际 period 对=`20241231 != 2024`；最小场景=`checks=1, issues=0`

## C4

- 阶段：C4 web_fetch 能力选择与执行
- 状态：COMPLETE
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_dynamic_capability tests.unit.test_researcher_search_budget tests.unit.test_tavily_search -v`
- 通过判据(具体字符串或数字)：financial/event selected 含 `web_fetch`；criterion 非空；DecisionGate blocked=0；fetch tool event 与预算扣减存在
- 失败含义：Agent 仍只看搜索摘要或绕过能力/预算契约
- 原始输出：定向组合最终 `Ran 16 tests in 0.037s`、`OK`；C8 selected=`structured_data_provider,web_fetch,web_search`，blocked=`0`

## C5

- 阶段：C5 检索查询生成升级
- 状态：COMPLETE（结构守卫成立；不宣称优于人工基准）
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python _collab/019c_instrument_viability/run_c5_queries.py`; `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_replan_query_guard -v`
- 通过判据(具体字符串或数字)：六题各 3 条共 18 条；无问号/问句词/内部串；长度<=180；已知实体含 symbol 或“公司”
- 失败含义：查询仍是整句问法、缺少消歧或放宽了 019-B 守卫
- 原始输出：`Q01-1` 至 `Q28-3` 共 18 行；`test_company_name_without_symbol_gets_company_disambiguator ... ok`；`test_query_uses_entity_identifier_facets_not_question_prose ... ok`

## C6

- 阶段：C6 报告分析关联性收紧
- 状态：COMPLETE
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest tests.unit.test_report_reader_guard -v`; 检查 C8 report
- 通过判据(具体字符串或数字)：详细分析不可追溯项=`0`；相关项共享关键发现 footnote 或 fact key；其他项进入 `## 补充事实`
- 失败含义：仍可仅搬移 bullet 绕过“分析关联”判据
- 原始输出：`test_llm_reader_render_normalizes_and_deduplicates_facts ... ok`；C8 detailed item 同时引用 `[^3] [^2]`；untraceable=`0`

## C7

- 阶段：C7 Agent 一手证据正文闭合率
- 状态：COMPLETE（测量完成但阈值 FAIL，进入分支 F）
- 验收命令：`git show -s --format='%h %cI %s' 364b283 058e824`; 查看 `_collab/019c_instrument_viability/c7_measurement/result.json`
- 通过判据(具体字符串或数字)：指标 commit 早于脚本；query<=18；fetch<=30；LLM=0；六题均有闭合率与 URL 记录
- 失败含义：纪律失败或无法判断一手证据基础
- 原始输出：metric=`2026-07-25T11:35:05+01:00`；script=`2026-07-25T11:38:04+01:00`；`query_count=18`；`fetch_count=18`；APBEC=`0.0`；达标题=`0`

## C8

- 阶段：C8 零网络端到端复验
- 状态：COMPLETE
- 验收命令：`PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .venv/bin/python _collab/019c_instrument_viability/run_c8_zero_network.py`
- 通过判据(具体字符串或数字)：network_calls=0；11 flags；四类产物；citation closure=ok；blocked=0；contract passed；C1-C6 守卫绿
- 失败含义：修复破坏超集图、交付契约或零网络隔离
- 原始输出：`network_calls=0`；`superset_flags_enabled=11`；`status=done`；`audit_citation_closure=ok`；`agent_decisions=16`；`decision_gate_blocked=0`；`graph_contract_validation=passed_at_engine_init`

## C9

- 阶段：C9 报告、验收卡与提交
- 状态：COMPLETE
- 验收命令：`.venv/bin/python -m unittest discover -s tests`; `.venv/bin/python -m ruff check src tests scripts`; `git diff --check`; `git diff --name-only main -- data/golden_set docs/evaluation.md pyproject.toml`
- 通过判据(具体字符串或数字)：tests>=350、failures=0；Ruff 全绿；diff check 为空；冻结资产 diff 为空；报告/验收/019-D 影响齐全
- 失败含义：不得提交或声称本卡完成
- 原始输出：首次 full run=`Ran 357 tests in 16.251s`, XLSX 字节测试偶发 `failures=1`；隔离重跑=`Ran 1 test in 0.013s`, `OK`；不改代码/断言的完整重跑=`Ran 357 tests in 15.831s`, `OK`；`ruff 0.15.15`；`All checks passed!`；`frozen_asset_diff=empty`；另一次定向命令因测试类名写错为 `errors=2`，改正后=`Ran 16 tests in 0.037s`, `OK`
