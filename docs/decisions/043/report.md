# 043：领域边界棘轮

043 首先把 concrete finance import 与金融字面量的基线测量变成受版本控制的离线守卫。
初始基线为 `import_sites=6`、`literal_files=19`、`literal_hits=118`（词表版本见
`data/domain_boundary/finance_lexicon.json`）。随后核心直接 import 已降至 `0`；金融字面量
仍为 `18` 个文件、`93` 行。该机制防止债务增长，不等于完整的领域迁移已经完成。

本轮未获真实 provider 的新增成本授权，因此不执行付费端到端运行。
