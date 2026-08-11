# R138 — H14 Skills 运行集成

状态：COMPLETE

## 决定

Skills 达到 H2-ready。一次运行现在以 `selected / loaded / bypassed / failed`
四态记录 Skill 生命周期；加载失败明确降级并保留本地工作流，不再留下无法判断是否生效的
开关。

已加载 Skill 的名称、版本和完整内容 SHA-256 进入 manifest，也进入 trajectory request
快照。strict replay 会比较 recorded 与 replayed Skill 快照，Skill 内容或版本漂移不能静默
复用旧轨迹。

## 验收

- 四态 locator：4/4。
- manifest 名称/版本/摘要覆盖率：1.0，摘要与磁盘内容一致。
- 相同 Skill 快照 strict replay：1.0，报告 artifact 字节一致。
- 默认/显式关闭 Skill 的报告字节一致率：1.0；关闭时 Skill 文件读取数 0。
- 加载失败 degradation event：1；失败后报告保留：1。
- 真实变异将运行态 Skill 版本改为 `mutated` 后，守卫以
  `manifest_content_matches=0` 失败；恢复后通过。

## 边界

- `SKILL_PACKS_ENABLED` 默认仍为 false；H2 不代表金融默认开启或质量收益。
- Finance 仍是唯一产品 Skill/DomainPack；没有新增其他产品领域。
- 本轮付费调用：CNY 0。
