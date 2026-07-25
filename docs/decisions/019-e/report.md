# 019-E 执行报告：一手证据链路与单题真实研究包

日期：2026-07-25  
分支：`task/019e-primary-evidence`  
总体状态：**INCOMPLETE — 预登记分支 C，STOP 交 PM**  
金钱成本：**¥0；LLM provider 调用 0**

## 1. 结论先行

E0、E1、E2 和 E3 的最小循环解耦实现均完成且零网络全套闸门全绿；但本卡的核心验收没有通过，不能写“业务场景成立”。

Q26 真实运行的逐环证据如下：

1. Tavily 首轮返回 CATL 官方 PDF；
2. 通用规则把它标为 `primary`，重排结果第一，实际 fetch order 也是该 URL；
3. 真实 HTTP GET 成功，pypdf 解码成功，Source 中有 1965 字中文正文，`content_truncated=false`；
4. 手写 completion stub 为抽取片段做了空白归一化，返回的 `extract_text` 不再是 Source 正文的逐字子串；
5. Extractor 按合同拒绝该 claim，机械记录 `invalid_extract_text=1`；
6. 因此 CATL primary Source 没有进入 Evidence，`primary_evidence=0`；
7. 报告脚注虽对四条二手/unknown Evidence 闭合为 `ok`，但 `primary_cited=0`。

此外，运行产生 37 次 Tavily 查询，超过 E3 的 12 次上限。37 行均为成功响应，不是重试失败放大；主要来源是 Critic retry 在研究分支预算之外反复生成检索。研究 BranchBudget 只记录 10 个调用，却没有形成覆盖全图所有搜索入口的外部查询硬熔断。正文 GET 为 7 次；加上 E1 下载的 3 次 HTTP 尝试，本卡 E3 链路 HTTP 合计 10，仍在 20 次上限内。

由于 primary Evidence 未闭合且 Tavily 已超限，本轮不允许修 stub 后重跑，也不允许换题。按分支 C 停止 E4、E5；019-B 的 `REACHABLE=2 < 4` 与 STOP、019-C 的冻结 APBEC 定义和 APBEC=0 均保持有效。

## 2. E0：XLSX flaky 真因、修复与五次全量

### 真因

openpyxl 3.1.5 的 `save_workbook` 会在每次保存时把 `workbook.properties.modified` 覆盖为当前 UTC 时间。原测试比较两次 XLSX 的完整字节；两次导出跨越秒边界时，`docProps/core.xml` 的 modified timestamp 不同，ZIP 长度也可能变化。

修复前用可控 datetime 机械复现：

```text
cross_second_equal=False
first_length=6253
second_length=6255
```

### 修复

`structured_output.py` 在 openpyxl 保存后重建 ZIP，仅把 `docProps/core.xml` 的 modified 字段规范化为固定值；工作簿业务内容、浮点格式、集合顺序和断言强度均未改变。新增跨秒回归用例，明确验证两份 XLSX 字节完全一致。未使用 skip、xfail 或重跑掩盖。

### 五次连续全量原始末尾输出

```text
_collab/019e_primary_evidence/e0_full_run_1.txt
----------------------------------------------------------------------
Ran 358 tests in 15.538s

OK
_collab/019e_primary_evidence/e0_full_run_2.txt
----------------------------------------------------------------------
Ran 358 tests in 15.571s

OK
_collab/019e_primary_evidence/e0_full_run_3.txt
----------------------------------------------------------------------
Ran 358 tests in 15.730s

OK
_collab/019e_primary_evidence/e0_full_run_4.txt
----------------------------------------------------------------------
Ran 358 tests in 15.683s

OK
_collab/019e_primary_evidence/e0_full_run_5.txt
----------------------------------------------------------------------
Ran 358 tests in 15.702s

OK
```

## 3. E1：两份真实 PDF、候选实测与选型

### 输入身份与完整性

| 文件 | 发布方 URL | HTTP / 大小 / 页数 | SHA-256 | 身份边界 |
| --- | --- | --- | --- | --- |
| CATL 2022-070 | `catl.com/uploads/1/file/public/202208/20220824151859_xrc00u671j.pdf` | 200；222,224 bytes；3 页 | `6e20462a5a7f7743143a27430213c37ce26e72cbb631fe300c4243ae73bbcadf` | 公司公告 |
| 贵州茅台 2024 | `moutaichina.com/mtgf/articleFileDir/2025-04/08/a8931897311b4d4097b7c0b2bf3207d1.pdf` | 200；546,909 bytes；7 页 | `a7210a641289973f3f7fc4d4a2f3097f18346c5c621af1cc9960e4c9131642db` | 实际是“年度报告摘要”，不是年度报告全文 |

CATL 首次直接请求为 403；加入普通浏览器 User-Agent 与官网 Referer 后为 200。E1 下载共计 3 次 HTTP 尝试，已计入本轮链路账本。

### 实测对照

| 库 | CATL 字符 / CJK / � / 耗时 | 茅台摘要字符 / CJK / � / 耗时 | 依赖边界 |
| --- | --- | --- | --- |
| pypdf 6.14.2 | 1965 / 1386 / 0 / 0.037900s | 5952 / 3512 / 0 / 0.112036s | Python 3.12 无强制运行时依赖 |
| pdfminer.six 20260107 | 2023 / 1386 / 0 / 0.064346s | 6377 / 3512 / 0 / 0.202009s | 独立安装缺 `cryptography`；补齐后引入 cryptography/cffi 等非纯 Python 扩展 |

两份均为文本型 PDF，不是扫描图像。pdfminer.six 在“只装候选本体、不装依赖”的隔离目录中实际失败：

```text
ModuleNotFoundError: No module named 'cryptography'
```

补齐其依赖后可抽取，但违反本卡“只新增一个纯 Python、无 C 扩展依赖”的严格边界。pypdf 在两份文件上更快、中文无 replacement char、许可证 BSD-3-Clause，因此选 pypdf。

### 两份 PDF 的前 300 个抽取字符

CATL：

```text
1 
证券代码：300750        证券简称：宁德时代        公告编号：2022-070 
宁德时代新能源科技股份有限公司 
关于投资建设匈牙利时代新能源电池产业基地项目
的公告 
 
 
宁德时代新能源科技股份有限公司（以下简称“公司”或“宁德时代”） 于
2022 年 8 月 12 日召开第三届董事会第九次会议，审议通过《关于投资建设匈牙
利时代新能源电池产业基地项目的议案》，公司拟投资建设匈牙利时代新能源电
池产业基地项目，现将具体情况公告如下： 
一、 投资概况 
1、随着国外尤其是欧洲新能源行业的快速发展，动力电池市场持续增长，
为进一步深化公司全球战略布局、推动海外
```

贵州茅台：

```text
贵州茅台酒股份有限公司 2024年年度报告摘要 
公司代码：600519                                                  公司简称：贵州茅台 
 
 
 
 
 
 
 
 
贵州茅台酒股份有限公司 
2024 年年度报告摘要 
 
 
 
 
 
 
 
 
 
 
贵州茅台酒股份有限公司 2024年年度报告摘要 
 
第一节 重要提示 
1、 本年度报告摘要来自年度报告全文，为全面了解本公司的经营成果、财务状况及未来发展规
划，投资者应当到http://www.sse.com.cn/网站仔细阅读年度报告全文。 
 
2、 本公司董事会、监事会及
```

### 接入与下游闭合

- Content-Type 为 `application/pdf` 或 URL 后缀为 `.pdf` 时走 pypdf；HTML 保持原路径。
- PDF 解码失败抛 `PdfDecodeError`，分类 `PERMANENT`，fail closed。
- `DEEPRESEARCH_PDF_MAX_PAGES` 默认 100；同时沿用正文字符上限；截断写入 Source 与 Evidence 的 `content_truncated=true`。
- fetch 走 ContractSearchProvider 的 ReliableToolExecutor、retry、circuit breaker、degradation event 与 trajectory。
- 生产重放：CATL `evidence_count=2`、脚注 2 条、`citation_present=true`；茅台摘要 `evidence_count=1`、脚注 1 条、`citation_present=true`。

### 依赖一致性

```text
pyproject.toml:  "pypdf==6.14.2",
.github/workflows/ci.yml:  "pypdf==6.14.2"
installed version: 6.14.2
License-Expression: BSD-3-Clause
Python >=3.11 mandatory dependencies: none
```

本卡只新增 pypdf 一个项目依赖。落选的 pdfminer.six 仅在 ignored 隔离目录做实测，没有进入项目依赖。

## 4. E2：一手源规则表、重排与真实抓取顺序

### 集中规则表全文

| 规则组 | 完整值 | 层级 / 意义 |
| --- | --- | --- |
| 法定披露域名后缀 | `cninfo.com.cn`, `sse.com.cn`, `szse.cn` | primary |
| 监管/政府后缀 | `gov.cn`, `csrc.gov.cn`, `pbc.gov.cn`, `stats.gov.cn`, `samr.gov.cn` | primary |
| 行业协会示例后缀 | `amac.org.cn`, `china-cba.net`, `sac.net.cn` | primary；刻意不含 019 六题域名 |
| 显式 source_type | `official`, `company`, `regulator` | primary |
| 官方发布路径 | `/announcement`, `/announcements`, `/disclosure`, `/investor`, `/press/`, `/upload/`, `/uploads/`, `/articlefiledir/` | 非云存储宿主时 primary |
| 云存储排除 | `amazonaws.com`, `aliyuncs.com`, `myqcloud.com` | 路径命中不自动当 primary |
| 官方正文标记 | `本公司及董事会全体成员保证`, `官方网站`, `投资者关系` | primary |
| 二手 source_type | `blog`, `news`, `social` | secondary |
| 其余 | 无命中 | unknown |
| 层级顺序 | `primary=0`, `unknown=1`, `secondary=2` | 小值优先 |
| 同层格式顺序 | HTML 在 PDF 前 | 优先可直接使用的 HTML 正文 |
| 稳定性 | 以上均相同时保留原始顺序 | 确定性 |

规则不含 CATL、茅台、Q01/Q04/Q16/Q19/Q26/Q28 的具体域名或题面。公司官网不是仅凭任意主域名硬编码判断，而由官方路径、正文标志或已有 source_type 合同识别。

### 构造候选重排与抓取

```text
BEFORE=[
  "https://media.example/story",
  "https://issuer.example/uploads/disclosure.pdf",
  "https://issuer.example/investor/news/disclosure",
  "https://research.example/article"
]
AFTER=[
  "https://issuer.example/investor/news/disclosure",
  "https://issuer.example/uploads/disclosure.pdf",
  "https://research.example/article",
  "https://media.example/story"
]
FETCH_ORDER=["https://issuer.example/investor/news/disclosure"]
SEARCH_RECORDS=[
  "query",
  "[web_fetch] https://issuer.example/investor/news/disclosure"
]
CALLS=2
EXHAUSTED=false
```

`source_rerank` AgentDecision 的 criterion 原文：

```text
rank exchange, statutory, regulator, association, and generic official-publication
paths ahead of unknown and secondary sources; prefer HTML to PDF within the same
tier; fetch in ranked order until a primary body is hydrated or candidates/budget
are exhausted
```

`alternatives_considered` 包含被跳过的 primary PDF 与 media 候选。Decision 经 research_join 的 NodeContract decision node 和 DecisionGate。

### 下游

- Extractor 把 Source 的 tier/truncated 机械复制到 Evidence。
- SQLite 迁移并持久化两个字段。
- 报告只要存在非 unknown 或截断证据，参考来源逐条显示 `[source_tier=...]`。
- 审计 Evidence JSON 显示 `source_tier` 与 `source_content_truncated`。
- 仅二手来源支持的结构化对象可通过其 evidence id 反查 tier。
- 默认确定性路径不开启该决策，不改变既有 golden。

## 5. E3：Q26 真实研究包与机械诊断

### 运行配置与产物

- `DEEPRESEARCH_MODE=llm`；
- Planner、Extractor、Reporter completion 均为本地手写 typed stub；
- stub usage 为 0；LLM provider 调用 0；金钱成本 ¥0；
- Tavily 与 HTTP 均为真实请求；
- `dynamic_capability_enabled=true`、`branch_budget_enabled=true`、`research_loop_enabled=true`、`max_iterations=4`、`no_progress_window=2`（未放宽）；
- 产物：`report.md`、`structured.{json,md,xlsx}`、`audit_bundle/`、`research_snapshot.json`、`trajectory.json`。

预飞行第一次在网络前被 `ConfigurationError: Missing required configuration: DEEPSEEK_API_KEY` 拦截；这是 fail-fast 读取进程环境而非 stub env 文件所致。失败目录保留，网络计数 0。设置假 key 到当前进程后才启动真实运行；该 key 只满足校验，completion_func 仍为本地 stub。

### 网络、LLM 与闭合数字

```text
llm_provider_calls=0
stub_completion_calls=40
tavily_queries=37      # FAIL: 上限 12
http_fetches=7
e1_prior_http_attempts=3
e3_total_http_chain_attempts=10
primary_source_count=1
primary_source_chars=1965
primary_evidence=0     # FAIL
primary_cited=0        # FAIL
citation_closure=ok    # 仅四条 unknown Evidence 内部闭合
decision_gate_blocked=0
```

Tavily ledger 37 行全部 `success=true`、`error_type=null`。重复最多的查询来自 Critic retry：

```text
AI agent financial advice risk compliance counterargument: 8
东方财富资讯 ...: 6
宁德时代匈牙利工厂将于2025年投产 ...: 6
宁德时代：匈牙利工厂将于2026年初投产 ...: 6
投资超600亿，宁德时代又一工厂将投产 ...: 6
```

因此超限不是 HTTP/Tavily 失败重试，而是不同图路径的逻辑查询没有共享 run-wide 外部熔断。研究 BranchBudget 最终 `used=10`，不能代表全图真实外部查询数。

### 一手 PDF 的逐环证据

| 环节 | 机械证据 | 判定 |
| --- | --- | --- |
| 检索返回 | search record 首项为 CATL 2022-070 URL | 通过 |
| 层级判定 | `source_tiers={CATL URL: primary}` | 通过 |
| 重排 | original=ranked=[CATL URL] | 通过 |
| 实际抓取 | `fetch_order=[CATL URL]` | 通过 |
| PDF 解码 | Source type=`web_fetch_pdf`，chars=1965，truncated=false | 通过 |
| 进入 Evidence | Extractor `invalid_extract_text=1`，claims=0 | **失败** |
| 报告引用 | primary Evidence=0，primary cited=0 | **失败** |

失败的直接原因是 harness 函数先执行 `re.sub(r"\s+", " ", content)`，再从压平文本切片作为 `extract_text`；该切片不再是含原始换行的 Source 正文逐字子串。Extractor 的 `claim.extract_text not in source.content` 防护正确拒绝，不能放宽。

### 单题研究包关键章节原文

```text
## 摘要
本研究包用于核验宁德时代匈牙利工厂时间线与产能口径。文字由手写 completion
stub 生成，只能证明证据链路与结构，不能证明模型生成质量；日期冲突须按各披露
时点并列阅读。

## 关键发现
- 德布勒森市投资73亿欧元（约合609.41亿元人民币）建设的工厂预计于2026年
  年初开始生产。... 新工厂规划年产能高达 100GWh ... [^1]
- 宁德时代匈牙利工厂将于2025年投产 考虑在欧洲开展电池回收业务 首页 金融
  公司 ... [^2]
- 东方财富资讯 评论 点击阅读全文 前往东方财富APP阅读全文 ... [^3]

## 风险与限制
- 不同披露时点可能分别使用项目启动、产线调试和商业投产口径，不能合并为单一日期。
- 本报告未调用真实 LLM，stub 的取舍不代表分析师级生成质量。

## 参考来源
[^1]: 投资超600亿，宁德时代又一工厂将投产！|宁德时代_新浪财经_新浪网.
       https://finance.sina.com.cn/roll/2025-09-08/doc-infpuftp4676665.shtml
[^2]: 宁德时代匈牙利工厂将于2025年投产 考虑在欧洲开展电池回收业务.
       https://m.caixin.com/m/2024-11-21/102261066.html
[^3]: 东方财富资讯.
       https://wap.eastmoney.com/a/202603103667564643.html
[^4]: 宁德时代：匈牙利工厂将于2026年初投产.
       https://www.guancha.cn/qiche/2025_09_08_789386.shtml
```

完整原始报告位于 `_collab/019e_primary_evidence/e3_q26_package/report.md`，未做人工编辑。

### 五条人工通读评语

1. 真实分析师不会把这份报告直接用于工作。最先卡在标题下的“`数据截至：1970-01-01`”：web fetch 没有解析发布日期，读者无法判断 2025/2026 说法的时点有效性。
2. 报告确实并列出现“`预计于2026年年初开始生产`”与“`将于2025年投产`”，风险节也写了“`不能合并为单一日期`”；但它没有按公告日期、产线调试、商业投产三个口径做证据比较，只是把两个说法放在不同长段落里，尚不能帮助分析师裁决冲突。
3. 关键发现的证据层级不能一眼看出。参考来源只有 URL，没有 `[source_tier=primary]`，因为实际被引用的四条 Evidence 都是 unknown；唯一 primary CATL PDF 没进入 Evidence。
4. 第三条关键发现从“`东方财富资讯 评论 点击阅读全文 前往东方财富APP阅读全文`”开始，是导航/推荐噪声，不是研究结论。它证明 stub 选择与 HTML 正文清洗不足会直接污染报告。
5. 边界声明是诚实的：“`只能证明证据链路与结构，不能证明模型生成质量`”以及“`stub 的取舍不代表分析师级生成质量`”均明确出现；但本轮连证据链路也只走到 Source，不能据此声称结构端到端成立。

### 最小循环解耦

原 progress 使用已饱和的 sufficiency score。现改为：

```text
unique deduplicated Evidence
+ independent Evidence URL domains
+ distinct primary Evidence URLs
- unresolved Critic issue count
```

完整分量写入 `research_progress_components`；BoundedLoop AgentDecision 的 inputs 与 criterion 均显示该量。未修改 sufficiency 的语义、公式、阈值，未删除 `max_iterations`、`budget_ceiling`、`no_progress_window`，未放宽 `no_progress_window=2` 或任何默认值。

实际轮数与停止：

```text
iteration 1: metric -2, no_progress_count 1, continue
iteration 2: metric  3, no_progress_count 0, continue
iteration 3: metric  3, no_progress_count 1, continue
iteration 4: metric  3, no_progress_count 2,
             stop_exhausted:max_iterations+no_progress_window
```

它没有复现旧的第 3 轮提前停止，因此不属于分支 E；但第二轮研究预算已耗尽，第三、四轮没有新证据，停止是正确的。

## 6. E4：冻结 APBEC v2 未运行

分支 C 明确要求 STOP 后续。E3 已经超过 Tavily 12 次上限，再运行 E4 会扩大外部网络写账本并违反任务卡。因此没有生成 `primary_evidence_closure_result_v2.md`，不能伪造 v2 数值或变化归因。

| 题号 | 019-C v1 闭合率 | 019-E v2 | 变化原因归类 |
| --- | ---: | ---: | --- |
| Q01 | 0/3 = 0 | N/A | E3 分支 C STOP，未测；不能归入 ①–④ |
| Q04 | 0/3 = 0 | N/A | 同上 |
| Q16 | 0/2 = 0 | N/A | 同上 |
| Q19 | 0/4 = 0 | N/A | 同上 |
| Q26 | 0/3 = 0 | N/A | 单题 Source 已解码但未进入 Evidence；这不是冻结 APBEC v2 测量 |
| Q28 | 0/3 = 0 | N/A | E3 分支 C STOP，未测；不能归入 ①–④ |

因为没有 v2 闭合项，所以没有可以附的 v2 URL/正文命中位置。019-C 的 v1 仍为 APBEC 0、0/6；冻结阈值仍为宏平均 `>=2/3` 且至少 4/6 单题 `>=2/3`。

019-B 的 `REACHABLE=2 < 4` 与 STOP **未修改、未重评、未替代**。本卡没有解除付费 STOP。

## 7. E5：未运行

E5 是分支 C 后的“后续阶段”，依预登记 STOP 未执行。没有 E5 网络调用，也没有把此前 019-C 的 C8 包冒充为本卡 E5 结果。

E3 后仍执行了移除 API key 的全套零网络闸门，证明仓库改动未破坏默认路径；这不等价于 E5 的 11 开关超集产物验收。

## 8. 新增守卫与防回归目标

| 阶段 / 测试 | 防止的回归 | 移除阶段改动时的失败方式 |
| --- | --- | --- |
| E0 跨秒 XLSX | openpyxl modified 时间导致字节漂移 | 删除 core.xml 规范化后，可控跨秒断言 `bytes1 == bytes2` 失败 |
| E1 中文 PDF→Evidence | 只得到 bytes/Source，未进入 Evidence | 删除 PDF 分支或 tier 传递后 evidence 非空/中文/tier 断言失败 |
| E1 坏 PDF | 静默空字符串 | 删除 PdfDecodeError 后 structured permanent error 与 attempts=1 断言失败 |
| E1 页数上限 | 大文件无界与截断不可见 | 删除页限或标记后 Source/Evidence truncated 断言失败 |
| E1 脚注闭合 | 解码文本不能被引用 | 删除 Evidence/footnote 接线后 mapping 与 citation 断言失败 |
| E2 primary 优先 | 二手候选仍排前 | 删除 rerank 后候选顺序断言失败 |
| E2 抓取顺序 | 只测排序、执行仍按旧序 | 删除 ordered fetch 后 provider calls 断言失败 |
| E2 预算停止 | 多候选越过分支预算 | 删除 consume_call 后 call ceiling 断言失败 |
| E2 tier 来源 | 测试/人工直接赋 primary | 绕过 classifier 后生成层级断言失败 |
| E2 报告 tier | 层级未到读者 | 删除 Reporter 呈现后参考来源字符串断言失败 |
| E2 AgentDecision/Gate | 决策未审计或绕过 NodeContract | 删除 join 记录或 decision_node 后合同验证失败 |
| E3 持续进展 | sufficiency 饱和导致第 3 轮提前停 | 恢复旧 metric 后迭代 3 出现 no_progress stop |
| E3 真停滞 | 新 metric 让死循环不停止 | 删除 no-progress 递增后 window=2 停止断言失败 |

“移除改动时失败”是针对每个守卫的机械 mutation 方法说明；本轮没有实际回退已提交代码或改写历史。没有弱化、删除、skip、xfail 任何既有测试。

测试文件改动理由：

- `test_structured_output.py`：补跨秒字节确定性与 source tier 输出。
- `test_tavily_search.py`：四项 PDF 下游守卫。
- `test_primary_source_ranking.py`：分类、排序、实际抓取、预算、层级、报告等守卫。
- `test_dynamic_capability.py`：research_join 的 DecisionGate 合同。
- `test_audit_bundle.py`：审计层级可见。
- `test_structured_data_provider.py`：SQLite tier/truncated 持久化。
- `test_prior_memory.py`、`test_researcher_search_budget.py`：新五元返回值与独立查询保留。
- `test_bounded_loop.py`：持续进展与真实停滞两种边界。

## 9. 链条完整性自查

| 修复点 | 上游改了什么 | 下游验证了什么 | 证据 | 结论 |
| --- | --- | --- | --- | --- |
| XLSX | 规范化 core modified | 完整 XLSX 字节 | 五次全量 + 跨秒测试 | 闭合 |
| PDF | GET 识别并 pypdf 解码 | Evidence 与脚注 | 真实 PDF replay + 四守卫 | fixture/生产 replay 闭合 |
| PDF 真实 Q26 | CATL PDF 解码成 primary Source | primary Evidence/引用 | `invalid_extract_text=1`、0/0 | **未闭合** |
| rerank | 通用规则排序 top3 | 实际 fetch order | E2 log 与 AgentDecision | 闭合 |
| tier | Source 规则赋层级 | Evidence/SQLite/报告/审计 | 七守卫与 E2 全量 | 闭合 |
| loop | 新最小进展量 | AgentDecision、真实迭代停止 | 2 守卫 + Q26 四轮 | 闭合 |
| 外部预算 | BranchBudget 约束研究分支 | 全图真实 Tavily 次数 | 10 vs 37 | **未闭合** |

回答铁律 15：本卡没有把 Q26 的 Source 成功冒充 Evidence 成功；失败正是在下一环被发现。也没有把 Tavily 的研究分支计数冒充全图外部请求计数。

## 10. 验证闸门

E3 提交前零网络全套：

```text
$ env -u DEEPSEEK_API_KEY -u DASHSCOPE_API_KEY -u TAVILY_API_KEY \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  DEEPRESEARCH_SEARCH_PROVIDER=fixture \
  DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=fixture \
  DEEPRESEARCH_MODE=deterministic \
  .venv/bin/python -m unittest discover -s tests
----------------------------------------------------------------------
Ran 370 tests in 17.066s

OK

$ .venv/bin/ruff check src tests scripts
All checks passed!

$ PYTHONPATH=src .venv/bin/python scripts/check_prompt_drift.py
prompt drift guard passed: 5 prompts

$ ... .venv/bin/python -m unittest discover -s tests/chaos -v
----------------------------------------------------------------------
Ran 8 tests in 0.334s

OK

$ PYTHONPATH=src .venv/bin/python -m unittest tests.unit.test_snapshot_run -v
----------------------------------------------------------------------
Ran 2 tests in 0.081s

OK

$ PYTHONPATH=src .venv/bin/python scripts/build_site.py
built <repo-root>/site/dist
files 13
validation ok

$ git diff --exit-code -- tests/golden_output data/golden_set/v1 docs/evaluation.md
[no output, exit 0]
```

`EOF marker not found` 是坏 PDF fail-closed 守卫向 stderr 写出的 pypdf 诊断；测试随后通过，不是 suite failure。

## 11. 生产代码总量与冻结资产

```text
production_added=396
production_deleted=44
remaining_to_420=24
```

生产代码新增按 `git diff --numstat main -- src` 计算，不含测试、脚本、fixture 与 pypdf 本体。距离 420 行上界还有 24 行。

冻结资产：

```text
$ git diff --name-only main -- data/golden_set docs/evaluation.md tests/golden_output
[no output]
```

未修改 Golden Set、golden output、`docs/evaluation.md` 或任何评分契约。没有冻结资产元数据变更需要申报。

## 12. 遗留、风险与停止后的工单

1. **Run-wide 外部请求硬熔断缺失（高）**：BranchBudget 未覆盖 Critic retry。下一次触网前必须让所有 web_search/web_fetch 入口共享同一真实外部计数与拒绝边界，并记录轨迹；达到上限 fail closed。
2. **Stub 逐字 extract 预飞行缺失（高）**：在网络前对 stub 输出执行 `extract_text in source.content` 的离线合同测试；不得放宽生产 Extractor。
3. **primary Source→Evidence 未闭合（高）**：本卡核心失败；需要 PM 新授权后才能修 harness 并重新触网。
4. **HTML 清洗不足（中）**：报告含“东方财富资讯 评论 点击阅读全文”等导航噪声。
5. **web fetch 日期为 1970-01-01（中）**：报告数据截至失真，分析师无法做时点判断。
6. **APBEC v2 与 E5 缺失（高）**：不是推迟包装，而是分支 C STOP 的直接结果。
7. **真实模型质量未知（高）**：stub 包不能证明模型冲突综合、引用选择或文字质量。
8. **OCR 不支持（已知边界）**：本卡两份不是扫描件；扫描 PDF 仍需另行授权。

## 13. 对 019-F 与付费轮的影响

- 完整 `ResearchProgress` 因变量重建仍必要，没有取消。当前四分量只证明可作最小解耦，不是最终权重设计。
- PDF 与 rerank 已提供正面工程基础，但付费实验的证据基础仍不成立：primary Evidence=0、primary cited=0、E3 查询超限、APBEC v2 未运行。
- 019-F 在任何真实网络或真实 LLM 支出前，应先零网络完成全图外部熔断和 stub contract 预飞行。
- 不自行修改 019-F 预登记参数、单项/总预算或回滚条件；是否继续由 PM 决定。

详见 `impact_on_019f.md`。

## 14. 诚实声明与自检

### 机械验证

- XLSX 真因复现、五次全量、跨秒守卫；
- 两个库对两份真实 PDF 的字符数、中文数、replacement、耗时；
- PDF Source→Evidence→脚注的测试/production replay；
- E2 重排、抓取次序、预算、层级、DecisionGate；
- Q26 Source、Evidence、footnote、搜索账本、loop tracker；
- 全套 unittest/Ruff/prompt drift/chaos/characterization/site/frozen diff。

### 人工判读

- 两份 PDF 中文是否可读、是否扫描；
- 五条研究包可用性评论；
- pypdf 与 pdfminer 依赖边界的工程选型；
- 对 019-F 的建议。

### 尚无证据支持

- 真实 LLM 的研究/写作质量；
- APBEC v2；
- E5 11 开关超集；
- 业务场景成立；
- 付费实验应获授权。

### 逐条自检

1. 有没有只修 PDF 解析、不验证下一环？没有：E1 fixture/replay 验证到 Evidence/脚注；E3 又真实验证并发现下一环失败。
2. 有没有只修排序、不验证执行？没有：构造 provider 的实际 fetch order 与 Q26 实际 CATL fetch order 都有日志。
3. 有没有把 Source 当 Evidence？没有：明确报告 1965 字 primary Source 与 0 primary Evidence。
4. 有没有把引用闭合 `ok` 当一手闭合？没有：`ok` 仅说明四条 unknown Evidence 的脚注内部闭合。
5. 有没有把 BranchBudget=10 当 Tavily=10？没有：真实账本为 37，并据此判超限。
6. 有没有把可在 ¥0 验证的东西默默推到下一轮？没有：已在本卡完成零成本 PDF/rerank/loop 守卫和一次真实 Q26；剩余真实重跑因本卡网络预算已超与分支 C STOP，需要新授权。
7. 有没有为了好看手工编辑研究包？没有：报告原样保存在产物目录；本报告只引用其原文并评论。
8. 是否更生产化？PDF fail-closed、通用 tier、审计传递、最小 progress 更生产化；但全图外部熔断与日期解析仍是明确生产缺口。
9. demo-only 风险？手写 stub 选择器与 Q26 runner 是 ignored 验证 harness，不进入产品；核心规则不含六题硬编码。
10. 是否保留默认 MVP 行为？是；golden characterization 通过，新增 content-affecting 能力仍由既有 dark flags 控制。

## 15. 提交与仓库原始输出

提交均为 conventional commits，无 Co-Authored-By，未 push、merge、tag、rebase 或 amend。

`git log --oneline main..HEAD` 原始输出：

```text
03f424c fix: measure research loop evidence progress
7775a14 feat: prioritize and label primary sources
0b5e26c feat: decode primary-source pdf evidence
300383a fix: stabilize xlsx core metadata
```

`git diff main --stat` 原始输出：

```text
 .env.example                                     |   1 +
 .github/workflows/ci.yml                         |   1 +
 pyproject.toml                                   |   1 +
 scripts/measure_primary_evidence_closure.py      |   2 +-
 src/deepresearch_agent/agents/extractor.py       |   4 +
 src/deepresearch_agent/agents/reporter.py        |  32 +++-
 src/deepresearch_agent/agents/researcher.py      |  87 +++++++++--
 src/deepresearch_agent/audit_bundle.py           |   2 +
 src/deepresearch_agent/orchestration/loops.py    |   9 +-
 src/deepresearch_agent/schemas.py                |  10 ++
 src/deepresearch_agent/settings.py               |   2 +
 src/deepresearch_agent/storage/sqlite_store.py   |  13 +-
 src/deepresearch_agent/structured_output.py      |  11 +-
 src/deepresearch_agent/tools/contract_adapter.py |  54 ++++---
 src/deepresearch_agent/tools/search_factory.py   |   1 +
 src/deepresearch_agent/tools/source_ranking.py   | 114 ++++++++++++++
 src/deepresearch_agent/tools/tavily_search.py    |  50 ++++++
 src/deepresearch_agent/workflow/engine.py        |  51 ++++++-
 tests/fixtures/catl_2022_070_excerpt.pdf         | Bin 0 -> 206377 bytes
 tests/unit/test_audit_bundle.py                  |   7 +
 tests/unit/test_bounded_loop.py                  |  69 ++++++++-
 tests/unit/test_dynamic_capability.py            |   7 +
 tests/unit/test_primary_source_ranking.py        | 184 +++++++++++++++++++++++
 tests/unit/test_prior_memory.py                  |   2 +-
 tests/unit/test_researcher_search_budget.py      |   3 +-
 tests/unit/test_structured_data_provider.py      |   4 +
 tests/unit/test_structured_output.py             |  20 ++-
 tests/unit/test_tavily_search.py                 |  91 +++++++++++
 28 files changed, 783 insertions(+), 49 deletions(-)
```

最终 tracked 工作区在报告生成前为 clean；`_collab/`、运行数据库、PDF 原件、真实正文、站点构建与所有报告均位于 `.gitignore` 覆盖路径。

## 16. 最终判定

**INCOMPLETE — 分支 C，STOP。**

可以证明：

- XLSX 输出确定性缺陷已修；
- pypdf 能解码两份真实中文一手 PDF；
- Agent 能召回、重排、抓取并解码 Q26 CATL primary PDF；
- 通用来源分级与最小 loop progress 有机械守卫；
- 默认路径 370 tests 与全部闸门全绿。

不能证明：

- primary 正文已进入 Q26 Evidence；
- 至少一条 primary 关键发现被引用；
- E3 满足 Tavily 12 次上限；
- APBEC v2 达标；
- 分析师业务场景成立；
- 可以进入付费轮。

交 PM 决定是否为“全图外部请求硬熔断 + stub 逐字合同预飞行 + Q26 单次受控重跑”另行授权。

