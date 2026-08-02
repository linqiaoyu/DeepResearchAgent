# 053：轮次过程资产出仓

gate 不再执行 047 专属计划台账检查。所有原 `data/round/` 过程资产（043、044、047）
已归档到各自的 decisions 目录；仍有消费者的路径同步更新。`check_plan_ledger.py` 移至
`scripts/round/`，保留为可手工运行的历史审计工具而不是跨轮 CI gate。
