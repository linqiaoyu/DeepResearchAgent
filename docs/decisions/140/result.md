# R140 — H16 Memory 持久化与接线

状态：COMPLETE

## 决定

Memory 达到 H2-ready。SemanticMemory 现在和 Episodic/Procedural 一样复用
`MemoryRecord` 与现有 `StorageProtocol`，绑定 durable store 时才声明 persistent；三类
persistent Memory 均可由全新进程读回。

Procedural write 从 Reflection 节点的隐式依赖中拆出：启用 Procedural Memory、关闭
Reflection 的完整运行仍在 Reporter 前写入确定性策略观察；Reflection 开启时仍提供更丰富
signals，且不会重复写入。

## 验收

- 三类 persistent 新进程读回：3/3，比例 1.0。
- StorageProtocol Memory 方法契约覆盖：1.0；SQLite/Postgres 共用同一契约：2/2。
- Reflection 关闭时 procedural 写入：3 条。
- tenant/domain 泄漏：0。
- Semantic namespace 生产变异使跨进程读回降至 2/3，守卫失败；恢复后通过。
- H2 不改变 Memory 默认开关，也不宣称金融质量收益。
- 本轮付费调用：CNY 0。
