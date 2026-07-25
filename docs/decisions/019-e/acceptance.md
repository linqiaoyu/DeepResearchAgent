# 019-E 验收卡

## E0

阶段：E0 分支、基线与 XLSX flaky 清除  
状态：PASS  
验收命令：`PYTHONPATH=src ... .venv/bin/python -m unittest discover -s tests`，连续执行 5 次  
通过判据：五次均为 `Ran 358 tests`、`OK`、0 failure  
失败含义：XLSX 导出仍受当前时间影响，确定性主张不成立  
原始输出：`e0_full_run_1.txt` 至 `e0_full_run_5.txt`，耗时依次 15.538s、15.571s、15.730s、15.683s、15.702s

## E1

阶段：E1 PDF 正文解码能力  
状态：PASS  
验收命令：两份真实 PDF 的 pypdf/pdfminer 实测；`python -m unittest discover -s tests`  
通过判据：pypdf 两份均 0 replacement char；四项 PDF 守卫全绿；`pypdf==6.14.2` 在项目与 CI 精确一致  
失败含义：一手 PDF 无法进入 Evidence 与脚注契约，业务链路不可达  
原始输出：CATL 1965 字、茅台摘要 5952 字；E1 全量 `Ran 362 tests`、`OK`

## E2

阶段：E2 一手源识别、rerank 与来源分级  
状态：PASS  
验收命令：`python -m unittest discover -s tests`；`e2_rerank_fetch_log.txt`  
通过判据：七项守卫全绿；构造候选中 HTML primary 排首；真实 fetch order 与重排一致；报告/审计/SQLite 可见层级  
失败含义：Agent 仍会只抓首位或无法把规则生成的层级传到下游  
原始输出：E2 全量 `Ran 368 tests`、`OK`；`FETCH_ORDER=["https://issuer.example/investor/news/disclosure"]`

## E3

阶段：E3 Q26 单题真实端到端研究包  
状态：INCOMPLETE — 预登记分支 C，STOP  
验收命令：`PYTHONPATH=src .venv/bin/python _collab/019e_primary_evidence/run_e3_q26.py`  
通过判据：provider=0；Tavily<=12；HTTP<=20；至少 1 条 primary Evidence 被关键发现引用；citation closure=ok  
失败含义：真实单题一手证据未端到端闭合，业务场景尚不成立  
原始输出：provider=0、Tavily=37、正文 GET=7（加 E1 共 10）；CATL primary PDF Source 1965 字，但 `invalid_extract_text=1`、primary Evidence=0、primary cited=0

## E4

阶段：E4 冻结 APBEC 六题重测  
状态：NOT RUN — E3 分支 C 要求停止后续  
验收命令：未执行，未产生任何 E4 网络调用  
通过判据：Tavily<=18、HTTP<=30、LLM=0；六题 v1/v2 并列且冻结阈值不变  
失败含义：若擅自继续会违反任务卡 STOP 与网络预算纪律  
原始输出：`E4 tavily=0, E4 http=0, E4 llm=0`；019-C v1 仍为 APBEC 0、0/6，019-B 仍为 `REACHABLE=2 < 4` 与 STOP

## E5

阶段：E5 零网络超集端到端复验  
状态：NOT RUN — E3 分支 C 要求停止后续  
验收命令：未执行  
通过判据：network_calls=0、四类产物、closure ok、DecisionGate blocked=0、契约通过  
失败含义：在分支 C 后继续实现卡会越过 PM 决策点  
原始输出：无 E5 产物；E3 后的全套闸门均在移除 API key 的零网络环境执行并通过

## E6

阶段：E6 报告、影响说明与提交  
状态：PASS（报告完成；总体任务仍为 INCOMPLETE）  
验收命令：`git log --oneline main..HEAD`、`git diff main --stat`、全套零网络闸门  
通过判据：报告逐环取证；验收卡六行规格；4 个 conventional commits；冻结资产零 diff；不 push/merge  
失败含义：无法让 PM 复核失败发生在哪一环及后续授权边界  
原始输出：`300383a`、`0b5e26c`、`7775a14`、`03f424c`；最终全量 `Ran 370 tests`、`OK`

