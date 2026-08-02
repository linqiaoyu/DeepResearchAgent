# 052：生产检索配置的离线 lexical 评测

在 retrieval_v1 dev 24 题上，带 domain entity/period 过滤和别名扩展的离线 lexical
臂得到 Recall@20=0.0972222222、nDCG@10=0.0110028384。12 题触发 entity facet，所有
24 题的标注都在过滤后的候选池内，但只有 4 题进入 lexical 排名，表明主要瓶颈是中文
问题与英文语料的词法不对齐，而不是 facet 过滤丢失标注。

4b 未执行：它需要额外的付费授权。
