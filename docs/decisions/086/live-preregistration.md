# 086 Live 预登记

登记时间：2026-08-02（UTC；逐次精确时间另记执行报告）

实现 commit：`f0f33ea5844e09f312d4d8bf0172ca5de3dbd8e3`。两次主运行必须保持该
commit；预登记与运行产物不改变源码。

## 假设与测量

1. NIO 的“关键发现”章节同时包含 `65,731,559,000 CNY` 与
   `6,492,762,000 CNY`，且该章节的“未取得”计数为 0。用
   `scripts/check_reader_visible_contract.py` 的章节切分断言测量。
2. 两份报告脚注标题/URL 的非目标期 annual report/results 与
   `forecast`/`预测` 特征计数均为 0。
3. SEC Company Facts 结构化 Evidence 的脚注 `source_tier=primary`，provider identity
   为 `SecCompanyFactsProvider`。
4. 每次各自满足 `off_year_ratio <= 0.20`、错误页脚注 0、
   `footnote_count == distinct_source_urls`、`primary_sources > 0`、
   `footnote_misrefs=0`、`magnitude_mismatches=0`、
   `audit_citation_closure=ok`、`verdict=PASS`；NIO 另需 `sampled_numbers >= 2`。

## 固定配置

- 标的 1：`蔚来 2024 年年报的营收与毛利情况`。
- 标的 2：`PDD 2024 annual report revenue and gross margin`。
- 共同参数：`--as-of 2026-07-01 --depth 1 --mode live --allow-paid-api`。
- RAG 库：`data/runtime/085-assets.db`。
- RAG index：`finance_v1-43f11085-heading_page_first_1024_256`。
- 显式环境：`DEEPRESEARCH_STRUCTURED_DATA_PROVIDER=sec_companyfacts`。
- 不换模型、不调 top-k/rerank、不换标的；绝不使用
  `data/runtime/086-decoded-probe.db`。

## 三次额度与停止规则

- 第 1/3 次：NIO 中文主运行。
- 第 2/3 次：PDD 英文主运行。
- 第 3/3 次：仅当一次主运行因可指名的 transient/provider/命令构造失败而未形成可审计包
  时使用；不得为了改善指标重跑。
- 任一次触发 Settings 既有成本/请求熔断即停止该项并保留失败；不得放宽熔断。
- 两次主运行完成后不使用剩余额度。

## 决策与回滚条件

- 若章节断言或来源治理断言失败，保留产物并标 INCOMPLETE；不得在同一代码上挑最好结果。
- 若运行揭示实现缺陷，需要改源码时，当前两次可比实验立即终止；修改后属于新实验，必须
  重新完整 gate，但不得突破剩余 live 次数。
- live 不写受管 fixture、golden set、047/085 语料库或 Qdrant；异常产物仅留在
  `artifacts/086/`、`runs/` 与 `_collab/086/`。

## 第 1/3 次后的预登记补充（执行第 2/3 次前）

第 1/3 次在原实现 commit 上形成了完整包，但来源治理把 HKEX URL 路径中的 2025
发布日期误判为报告期，错误拒绝目标 2024 年报；该次验收因此记为 FAIL，产物保留为
`artifacts/086/live-nio-zh-attempt1/`。没有为了指标挑选而重跑。

最小修复只区分“标题/显式 annual/FY URL 的报告期”和“普通 URL 发布日期”，新增实际
HKEX URL 反例后完整 gate 退出 0。最终 live 实现 commit 登记为
`4cdab3b76cd0f81942771752a50158f49081ef87`：

- 第 2/3 次：NIO 中文主运行重试；
- 第 3/3 次：PDD 英文主运行；
- 两次都必须保持 `4cdab3b76cd0f81942771752a50158f49081ef87`；额度用满即停。
