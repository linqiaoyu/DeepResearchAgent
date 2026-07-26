# 033 Agent 核心架构审计与重建

一句话结论：Extractor 与动态工具路由确实改变执行，修后的 working memory 只影响 prompt
预算视图；Critic 在冻结护栏未触发，procedural/episodic/replan 未激活，Reflector 仍是占位
装饰。基于消融，保留真正有合同证据的边界、把实验机制默认关闭，并用 typed grounded
facts 消除恒瑞长数字转写错误；最终 Flash/Pro 均 6/6、零幻觉数字，Flash 成本更低。

- [消融、跑分序列、保真与模型选型](ablation-and-results.md)
- [全部运行清单（含 mixed-provider）](run-register.md)
- [架构审计与重构边界](architecture-audit.md)
- [工具失败矩阵与失败回放](failure-matrix.md)
- [语义评价链路](semantic-evaluation.md)
- [AGENTS.md 重写与防漂移](agents-md-rewrite.md)
- [开源架构与许可证审查](open-source-review.md)

本轮没有更换编排框架、没有新增重型依赖、没有复制第三方代码。`engine.py` 仍是上帝对象，
finance domain-pack 也未完成；这些是显式未交付，不以局部接口抽取冒充领域无关架构。
