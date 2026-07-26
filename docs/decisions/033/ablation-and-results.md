# 033 Agent 核心消融与真实护栏结果

## 实验合同

冻结护栏 SHA-256 为
`dd0f2ca4ab5a7ec2676f4c45a6e407ea944fb986776db7e43e109be253d2dbc8`。题目、真值和
判分方式冻结后未修改。除明确标记的 Reflector/memory mixed-provider 实验外，运行的 LLM、
检索、结构化数据和公告通道分别为 DeepSeek/Qwen、Tavily、AKShare 与 CNINFO；每个 research
run 的成本熔断为 CNY 2.00。Reflector 实装仍返回 `synthetic_fixture / recorded_placeholder`，
所以那四条运行不称为“真实模式”。不同代码 commit 的重跑是新实验，同 commit 的重复运行
全部保留，不挑最优。

## 消融结论

“开/关结果”都是双案例汇总，格式为正确指标/6、幻觉数字、成本、耗时。早期结果仍会受
随机生成波动影响，因此判定同时要求 component activity/trace 证明该机制实际被调用。

| 对象 | 真实开/关证据 | 判定 | 本轮动作 |
|---|---|---|---|
| Critic | 开：control 6/6、H1、¥0.06688028、229.879s；关：6/6、H1、¥0.07106228、214.174s。开时两题均 0 issue、0 retry | **未被激活**（护栏上） | 保留默认开。fixture 注入只证明 typed issue 路由合同；不再声称护栏质量由它改善 |
| Reflector | 关：control 6/6、H1；开：2/6、H1、¥0.07497664、244.902s；activity 仅 `synthetic_fixture / recorded_placeholder`，0 nonempty signal、无同轮消费者/策略采用 | **装饰（当前实现）；真实模式消融 INCOMPLETE** | 保留但 quarantine 为默认关的实验接口；没有真实判断力/生产收益声称。因最后模型对照已执行，不追加违反顺序的新付费实验 |
| Extractor | 开：control 6/6、H1；关：1/6、H2、¥0.01623068、104.726s；关后 CNINFO Source 未转成 typed Evidence | **在干活** | 保留并明确边界：Researcher 取 Source/结构化 Evidence，Extractor 解析文档 Source |
| Working memory | 旧关：6/6、H1；旧开：5/6、H1、¥0.07597520、258.310s，并把 canonical Evidence 7→5/6 | **有害（旧实现）** | 修成只裁 prompt view，不改 canonical store。最终开：6/6、H0、¥0.12007676、267.307s，canonical 9/5 保留，prompt 7/4；现为**在干活**，仍默认关待大上下文验证 |
| Episodic memory | mixed-provider 同一 Engine 同题两次均 read=0，没有该场景写路径 | **未被激活；真实模式重复运行 INCOMPLETE** | 保留默认关，只定位为跨日期 ResearchSnapshot 能力；不宣称重复问答受益。因最后模型对照已执行，不追加违反顺序的新付费实验 |
| Procedural memory | 第一次 read=0/write=1，第二次 read=1/write=1，但两次 adopted=0；subquestion 与工具计数确有变化，因 adopted=0 不能归因于记忆 | **未被激活** | 另有全真实 off arm，但没有策略采用的全真实 on 对照；默认由 true 改 false，保留显式实验入口，必须用采用率和对照收益再转正 |
| replan / sufficiency | loop on：4/6、H1、¥0.07455620、242.839s；两题 iteration 1/2、无 boundary trigger，因 Evidence 层满足阈值而 `stop_sufficient`，replan 0 次；茅台 1/3 来自 Reporter 漏上年绝对值，不证明 Evidence 不足 | sufficiency **在干活（证据层）**；replan **未被激活** | 整体维持默认关，直到强制 insufficient 的真实 case 验证回边；另以 fixture 测试保证 sufficiency 与 max 同时成立时优先报 sufficient，不把“已足够”误报为上限耗尽 |
| Dynamic capability | 旧 off 3/6 是失真 control：固定集缺 disclosure/fetch，CNINFO 0、Tavily search 8。修复固定集后：off 6/6、H0、¥0.12773212、276.516s；on 6/6、H0、¥0.12403376、280.869s；authority fetch/Evidence 为 4/14 vs 5/16 | **在干活（改变路由），但本护栏无质量增益** | 保留默认开用于跨问题类型路由；固定集补齐同等可执行能力，不再把选择开关与工具可用性混为一谈，也不声称本护栏质量由它改善 |

Critic 的“未被激活”与 Reflector 的“装饰”不是同义词：Critic 有被 fixture 故障触发的合同
证据，只是双案例没有 issue；Reflector 在 live core pipeline 中被调用，却只产生合成占位
输出且无同轮消费者/策略采用，因此整个 arm 按常驻纯度规则只能称 mixed-provider。

## 护栏跑分序列

| 顺序 | label / commit | 正确指标 | 幻觉数字 | 成本 CNY | 耗时 s | 说明 |
|---:|---|---:|---:|---:|---:|---|
| 1 | baseline / `88c6f3e` | 4/6 | 0 | 0.06415172 | 213.105 | 冻结后 baseline |
| 2 | instrumented_control / `4c300ed` | 6/6 | 1 | 0.06688028 | 229.879 | component activity control |
| 3 | ablation_critic_off / `4c300ed` | 6/6 | 1 | 0.07106228 | 214.174 | Critic off |
| 4 | ablation_extractor_off / `4c300ed` | 1/6 | 2 | 0.01623068 | 104.726 | Extractor off |
| 5 | ablation_reflector_on / `4c300ed` | 2/6 | 1 | 0.07497664 | 244.902 | Reflector on |
| 6 | ablation_working_memory_on / `4c300ed` | 5/6 | 1 | 0.07597520 | 258.310 | 旧 working memory on |
| 7 | ablation_procedural_memory_off / `4c300ed` | 4/6 | 0 | 0.07616220 | 204.300 | 当时默认 on 的反向消融 |
| 8 | ablation_research_loop_on / `4c300ed` | 4/6 | 1 | 0.07455620 | 242.839 | max iterations=2 |
| 9 | ablation_dynamic_capability_off / `4c300ed` | 3/6 | 0 | 0.05497964 | 221.716 | 后证实固定集不公平，不能用于选型 |
| 10 | post_fidelity_flash / `6f1edeb` | 6/6 | 0 | 0.07661512 | 224.138 | typed grounded facts 初修 |
| 11 | final_dynamic_off_flash / `18411e3` | 6/6 | 0 | 0.10923528 | 258.710 | 冻结 scorer 绿；但全报告机械门发现 `.06→.6`，不算 final |
| 12 | final2 误配 / `606683d` | 茅台 3/3；恒瑞无分 | 0；无分 | 0.03379120 + 0.00442492 | 122.570 + planner 19.090 | 错误变量名；实际 dynamic on/judge off；第二 run 中断，不纳入 arm 比较 |
| 13 | final3_dynamic_off_flash / `606683d` | 6/6 | 0 | 0.12773212 | 276.516 | 公平 fixed control |
| 14 | final3_working_memory_on_flash / `606683d` | 6/6 | 0 | 0.12007676 | 267.307 | 修后 working memory |
| 15 | final3_flash / `606683d` | 6/6 | 0 | 0.12403376 | 280.869 | 最终 Flash |
| 16 | final3_pro / `606683d` | 6/6 | 0 | 0.30309540 | 405.679 | 最后才执行的 Pro |

冻结 scorer 只检查读者关键事实行；第 11 次暴露出“关键行正确但覆盖段错误”的盲区。
本轮没有改 scorer，而是让既有全报告机械 evaluator 阻断该运行，再修 typed coverage 渲染和
金额正则左边界。修复后的 final3 四个 arm（第 13–16 次）全报告机械门也为 1.0。

## 保真机制结果

报告关键事实不再让 LLM 重抄 typed 数字：通用 `GroundedFactRenderer` 协议由 finance
renderer 从 Evidence 机械生成读者行并绑定原 footnote；metric coverage 同样优先消费 typed
Evidence。金额归一使用 `Decimal`，且正则不能从分组小数的后两位开始误匹配。

恒瑞最终读者报告同时保留 `7,711,054,811.98`、`6,336,527,014.75` 与 `21.69%`；茅台
三项无回归。改一位、改量级、改小数点/方向仍全部被既有三档机械变异门拒绝。删除 Engine
wiring、entrypoint renderer、coverage typed render 或 grouped-decimal 左边界都会产生已保存
的定向红灯；strict replay 没有被用作质量证据。

## 模型对照与选型

| 模型 | 茅台 | 恒瑞 | 幻觉数字 | 语义 judge | 成本 CNY | 耗时 s |
|---|---:|---:|---:|---|---:|---:|
| `deepseek-v4-flash` | 3/3 | 3/3 | 0 | 茅台五维 1.0；恒瑞仅 answer-shape 0.9，其余 1.0 | 0.12403376 | 280.869 |
| `deepseek-v4-pro` | 3/3 | 3/3 | 0 | 五维 judge 分与 Flash 完全相同 | 0.30309540 | 405.679 |

Pro 成本增加 CNY 0.17906164（2.44365 倍），耗时增加 124.810s（1.44437 倍），没有质量
增益。本卡选择 Flash。结论只覆盖双案例，不宣称 Flash 在所有研究任务优于 Pro。

## 运行完整性与异常

总计 33 个完成 run（31 个 guardrail case + 2 个 memory probe），另有 1 个 planner 后人工
中断 run；其中 29 个完成 run 满足全真实模式纯度，Reflector arm 2 个和 memory probe 2 个
因 Reflector placeholder 归为 mixed-provider。中断 run 的已执行 planner/provider 配置为真实，
但它不是完整研究。全部 34 条可核实总成本 CNY 1.55554464；所有单 run 均低于 CNY 2.00。

`final2_dynamic_off_flash` 的命令误用了带 `DEEPRESEARCH_` 前缀的两个 bool 环境变量，导致
茅台实际为 dynamic=true、judge=false（run `2652a5a3-b0f5-42f3-a5b7-a08d81c9bbe2`，
CNY 0.03379120）；恒瑞 run `d633517e-bda0-4d0f-804d-25b80f5f5687` 在 planner 花费
CNY 0.00442492 后被中断。两条都计入成本和运行清单，不纳入 arm 比较。预登记声称目录
保留 traceback，但现场只有 ledger 与 SQLite 文件，没有 traceback；最终报告明确更正，
不补造缺失证据。更正后每个付费命令先以 `load_settings()` 做无网络配置断言，再执行
`final3_*` 新实验。
