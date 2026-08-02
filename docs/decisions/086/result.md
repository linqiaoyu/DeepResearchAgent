# 086 数字结论

## 重嵌入裁决

离线 BM25 对照使用 24 条 query、相同 `top_k=10`，原库为
`data/runtime/047-assets.db`，实验副本只做 HTML entity decode。原始输出归档于
`_collab/086/evidence/decode_impact.log`。

- `queries=24`
- `changed_queries=21`（87.50%）
- `mean_overlap_at_10=0.837500`
- `mean_rank_biased_overlap=0.749791`
- `top1_changes=10`
- `decoded_chunks=21856`
- `verdict=rebuild_justified`

判决规则在运行前写死为：`mean_overlap_at_10 >= 0.90` 且
`changed_queries / queries <= 0.20` 才输出 `rebuild_not_justified`；本次两项均不满足，
因此是否执行重嵌入的数字结论是：**是，`rebuild_justified`**。086 的硬边界禁止实际
重嵌入、重新分块或修改 Qdrant，所以执行必须留待另行明确授权的工作轮，本轮没有进行。

## 语料不可变性

原始输出归档于 `_collab/086/evidence/corpus_immutability.log`：

- `047-assets.db` 前后均为
  `ca6bac982bb3dc8b96151941e07e54995cb9e6b71da1e37b7f76283860404a2d`。
- `085-assets.db` 前后均为
  `31f82467ab3a24cfd7beb519386a3fd15e9ef49f58c76dd8263308e57b8ee4a0`。

## 离线交付数字

- 读者可见 contract：C1–C5 五个 mutation 均真实退出 `1`；正常 self-test 退出 `0`。
- 静默降级审计：`stages_covered=14`、`rows=26`、
  `rows_missing_columns=0`、`high_severity=12`、
  `high_severity_unaddressed=0`。
- domain boundary：`import_sites=0 literal_files=3 literal_hits=9 lexicon_terms=33`。
- pre-live 完整 gate：退出 `0`。

## Live 验证

三次额度全部使用；第 1/3 次揭示“HKEX URL 发布年被误当报告期”的分层缺陷，验收 FAIL，
同轮修复后，两个最终主包都在 commit
`4cdab3b76cd0f81942771752a50158f49081ef87` 上执行。

- NIO：关键发现 `2/2`，非目标期脚注 0，`off_year_ratio=0.00`，错误页脚注 0，
  `footnote/URL=17/17`，`primary_sources=10`，`sampled_numbers=2`，
  `footnote_misrefs=0`，`magnitude_mismatches=0`，`verdict=PASS`，
  `audit_citation_closure=ok`。成本为 `0.02421656 workflow + 0.019101 RAG =
  0.04331756 CNY`。
- PDD：非目标期脚注 0，`off_year_ratio=0.00`，错误页脚注 0，
  `footnote/URL=18/18`，`primary_sources=10`，`sampled_numbers=1`，
  `footnote_misrefs=0`，`magnitude_mismatches=0`，`verdict=PASS`，
  `audit_citation_closure=ok`。成本为 `0.02777992 workflow + 0.03766950 RAG =
  0.06544942 CNY`。SEC Company Facts 对“主营业务毛利率”返回 unsupported，报告显式 gap。
- 第 1/3 次失败包成本为 `0.026904 workflow + 0.019101 RAG = 0.046005 CNY`。
- 本轮三次 live 总成本：`0.07890048 workflow + 0.07587150 RAG = 0.15477198 CNY`。
