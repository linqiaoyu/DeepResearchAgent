# 048：四部分全面审阅与修复规划（审阅轮，不含修复）

- 基线：main @ d3c2bce（工作树干净）；任务卡明确只要求「审阅 + 出方案」，修复由后续轮次按 goal 卡执行（符合 AGENTS §2 例外条款）。
- 完整产物（审计正文、OSS 对标、goal 任务卡、复现原始日志）存于本轮 `_collab/048_full-audit-and-goal/`；本记录为脱敏自包含摘要。

## 门禁基线（干净 main）

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py < /dev/null`：绿。
`Ran 707 tests, OK (skipped=4)`；demo/eval smoke 与基线零漂移（avg_citation_accuracy=1.0、resolution=1.0、density=0.715）；tracked_files_unchanged 通过。
注意：不带 `< /dev/null` 时套件会在 unittest 阶段**永久挂起**（见 O9）。

## 主要发现（编号与严重级同审计正文）

### Agent Harness
- **H1【P1】`RAG_ENABLED=true` 默认引擎崩溃**：`EmptyRagSearchTool.search(*, query, as_of)` 不接受 `context`，而生产调用点 `agents/researcher.py` 总是传 `context=`；注册表无适配层。单元级与管道级均已复现（确定性 demo，5 个 research_one 分支全部 `TypeError`，run_failed）。现有测试只测无 context 形态，绿测掩盖断裂。
- **H2【P2】manifest flags 快照缺 RAG 三旗**：`FLAG_CLASSIFICATIONS` 已分类 `RAG_ENABLED/RERANK_ENABLED/RERANK_FAIL_OPEN`，但 `settings_flag_snapshot` 从不发射（可执行证据：include_disabled_experimental=True 时输出仍为空）。
- **H3【P2】`retrieval_index_version` 写侧断线**：全仓库无人写 `state.metadata["retrieval_index_version"]`，manifest 该可比性字段恒 None。
- **H4【P2】检索层不在 realness 证明面**：`_provider_usage` 把 `[rag_search]`/`[web_fetch]` 记录计入 search；`provider_fidelity` 无 rag/embedding/rerank；`RagSearchService.fidelity` 写死 "fixture"。
- H5-H8【P3】：engine `strategy_config` 手抄漂移（RAG 数值参数未入）；`QdrantIndex.query` 读路径可创建集合；`run_research_package.py` 用私有属性收尾、假 LLMClient 当台账、合成 run_id 记账；懒导出三处双标准无守卫。

### 金融投研 SUT
- **S1【P2】**：`FinanceDomainPack` 模块级加载 issuer 数据文件并做 IDF 匹配——数据文件缺损时引擎（即使 RAG 关闭）无法构造。
- **S2【P2】**：period 过滤自然年/财年错位（查询取 `20\d{2}`，payload 取财年截止年；3 月截止财年公司系统性错位）。
- S3/S4【P3】：`DomainPack` 协议 40+ 方法且含 demo/golden 专用与金融专名语义；legacy 域兜底使显式注入不可强制。

### 两者连接
- **C1【P1】语料与 SUT 平行世界**：RAG 语料是 60 篇英文 SEC 20-F（美股中概），SUT 主线是 A 股 CNINFO/AKShare/中文 golden——主 golden 公司不在语料也不在 issuer catalog，RAG 对被测系统核心任务无检索能力。
- **C2【P1】检索质量闭环空转**：冻结 BM25 基线 dev recall@20=0.0 / nDCG@10=0.0（中文问题×英文语料，词法臂结构性为零）；B5-5 付费实验（¥13.8 全量嵌入后 Recall@20=0.0128、nDCG@10=0.0，如实记 FAIL）测的是**无** entity/period 过滤与查询扩展的裸管道，不是生产配置——负结果不可归因。
- **C3【P1，需授权】**：renderer 修复后从未有过一次成功的真实三层 E2E（030 教训模式重演）；成功次数至今为 0。
- **C4【P2】**：空索引路径无 DegradationEvent，"开着但空"静默。
- **C5【P1】as-of 防前视被击穿**：`effective_date`（财年截止日）同时充当防前视日期与报告期——FY 截止后、披露前的窗口存在前视泄漏。需拆分 `published_at` 与 `period_end`。

### 其他
- **O1【P1】AGENTS.md 关键事实过时**：§1/§2 仍称域耦合未解、import 点 5→6；实测 `import_sites=0 literal_files=3 literal_hits=9`（Ruff TID251 + ratchet 双守卫在位）。
- **O2【P2】轮次机器泄漏**：`gate.py` 硬编码 047_plan_ledger 步骤；`data/round/` 轮次产物入 tracked 树；97 块单轮计划本身违反 §2 轮次切分原则。
- **O3【P2】ADR 与 pyproject 矛盾**：ADR 047 称 pdfplumber 仅 dev 依赖，实际已入 `[project.dependencies]`（提交 e4dc665，且该提交消息与内容不符）。
- **O4【P2】Git 卫生**：五对同名提交；047 合并提交（135 files/+13,688 行）复用分支尾提交消息。
- O5-O7【P3】：环境变量命名双轨；rerank 端点常量待核；docker 资产入库但从未执行。
- **O9【P3】测试套件读 ambient stdin**：mcp stdio 路径在 stdin 为开放管道的宿主下永久挂起（CI 的 /dev/null 掩盖）；本轮首跑门禁即因此挂起 23 分钟，`sample` 栈证实阻塞于 stdin `readall`。

## 修复规划（goal 卡摘要，每任务一轮、单命令量化验收）

| 任务 | 内容 | 授权 |
|---|---|---|
| T1 | 修 H1 崩溃 + 空索引显式降级（管道级验收：RAG_ENABLED=true demo exit=0 且 manifest 含 rag_search 降级事件） | 无 |
| T2 | manifest 补线：三旗发射 + 分类/快照一致性守卫 + index_version 写侧 + 检索用量/保真度一等公民 | 无 |
| T3 | `published_at`/`period_end` 拆分：语料 v2（v1 不动）、迁移、qdrant payload 回填、防前视合同测试 | 无 |
| T4 | 检索评测有效性：4a 生产过滤配置离线重测词法臂 + 逐问题根因数据；4b 付费 dev 复测（预注册，熔断 ¥2） | 4b 需授权 |
| T5 | 轮次机器出仓：gate 去 047 化、data/round 归档、scripts 分类清单 | 无 |
| T6 | AGENTS.md 事实修订（改为命令引用）+ ADR 047 勘误段 + README 复核 | 无 |
| T7 | （可选）DomainPack 瘦身 + domains 注册 entry_points 化（行为不变、快照逐字节不变） | 用户拍板 |
| T8 | 修复后首次真实三层 E2E 验证（预注册先行，单次熔断 ¥15） | 需授权 |
| T9 | P3 打包：懒加载 issuer、qdrant 查询只读化、strategy_config 派生、导出守卫、stdin 去依赖等 8 项 | 无 |

## 不利结论保留

- 真实三层 E2E 成功次数：0。
- B5-5 检索质量实验：FAIL（并且实验配置与生产配置不一致，结论不可归因）。
- 047 计划台账终态：90 PASS / 6 DEFERRED / 1 FAIL，带 FAIL 合入 main。
- 本轮首次门禁执行挂起（环境/命令构造问题，已按 §3 修正重跑并保留首跑输出）。
