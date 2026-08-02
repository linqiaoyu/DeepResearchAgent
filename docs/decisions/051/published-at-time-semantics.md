# 051：发布日期与报告期的时间语义

v1 语料与 retrieval_v1 golden 保持不可变。v2 在同一 60 条源文件记录上新增
`published_at`。本机没有可靠的本地归档日期索引，所以全部 60 条如实使用
`retrieved_at` 的日期上界并标记为 `retrieved_at_fallback`：这会延迟可检索性，
但不会泄漏披露前内容。

SQLite、Postgres、Qdrant 和服务级防御性过滤都以 `published_at` 判断 as-of；
`effective_date` 仍表示报告期并继续派生 period label。防前视守卫证明将 SQLite
比较改回 `effective_date` 会失败。
