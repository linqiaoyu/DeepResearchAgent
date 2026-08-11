# R139 — H15 Memory 生命周期统一

状态：COMPLETE

## 决定

四类 Memory 的真实生命周期和隔离维度进入机器合同：working 为 run-scoped；
episodic/procedural 在进程内为 cross-run，绑定 durable store 后才声明 persistent；
semantic 当前如实声明 cross-run，留待 H16 完成持久化后转为 persistent。

Durable namespace 现在由 tenant、domain、memory namespace 三部分组成，working memory
额外强制 run scope。新写入的 working/procedural 记录必须包含 as-of 与 provenance；
semantic 的 source URL 不再允许为空，episodic 继续以 snapshot as-of/manifest 为来源。

## 验收

- 四类登记、lifecycle、scope、provenance/as-of 覆盖率均为 1.0。
- 两类当前声明 persistent 的 Memory 均由全新子进程读回，2/2，比例 1.0。
- tenant/domain 泄漏 0；跨 run 访问被拒绝 1/1。
- 将未持久化的 SemanticMemory 错标 persistent 后，守卫以 lifecycle 覆盖率 0.75 失败。
- `memory` 保持 `wired`；H16 需使 semantic 成为真实 persistent、三类 persistent
  3/3 新进程读回，并解除 procedural write 对 Reflection 的隐式依赖后才能 H2-ready。
- 本轮付费调用：CNY 0。
