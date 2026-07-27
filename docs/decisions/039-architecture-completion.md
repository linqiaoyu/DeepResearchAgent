# 039：完成 038 架构审计的迁移决策

## 决策

039 将 038 中的架构级缺口纳入交付，而非仅记录为路线图。迁移遵循四个不可变约束：核心不含金融词表或 A 股检索策略；每次运行的可变预算/工具上下文不挂在 engine 实例；确定性运行不伪造真实计量；可选 provider/UI 不成为库核心安装依赖。

## 分阶段兼容策略

1. 新增 `DomainPack` 与 finance 实现，先将词表、期间解析、primary-source 策略和覆盖规则作为显式依赖注入；旧导入仅保留兼容转发。
2. `ResearchState.metadata` 成为 run-scoped budget/tool-context 的序列化事实源；engine 只在调用栈持有本次运行对象，禁止跨 run 复用。
3. 年报解析保留正则 fallback，但返回结构化 rejection、精确行锚点；fixture 增加 primary disclosure，进入端到端 smoke。
4. 确定性指标标明 synthetic，费用统一以 CNY 记账；citation density 与 semantic faithfulness 分列，gate 只比较同义指标。
5. `finance` 与 `ui` 改为 extras，Docker 镜像按服务安装所需 extra。

每阶段必须保持离线完整门禁可运行；不引入新的重型框架或外部 provider 调用。
