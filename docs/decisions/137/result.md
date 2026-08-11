# R137 — H13 Skills 合同

状态：COMPLETE

## 决定

Skill 包现在必须在 `SKILL.md` frontmatter 中声明自身版本和 Harness API
版本。发现阶段只读 frontmatter；只有确定选中后才能读取资源。Harness API 不兼容、
资源 symlink/路径逃逸、Capability 名称冲突均 fail closed，且冲突在任何注册前完成
预检。

Skill capability 继续只注册到统一 `CapabilityRegistry`，其成本和副作用必须与
`ToolSpec` 一致。默认 `ToolCallingLoop` 对付费 Skill 调用执行数为 0，因此 Skill
没有第二条执行或预算通道。

## 边界

- 没有新增产品 Skill 或第二 DomainPack。
- `SKILL_PACKS_ENABLED` 默认仍为 false，默认金融报告不变。
- 本轮只关闭 H13 合同；`skills` 保持 `wired`，待 H14 四态可观测、manifest 摘要和
  replay 合同完成后才能升为 H2-ready。

## 证据

- 数字 proof：`docs/decisions/137/skills-contract-proof.json`。
- 门禁：`scripts/check_skills_contract.py --self-test`，由 `scripts/gate.py` 传递执行。
- 真实变异：移除生产 Skill API 版本检查后，守卫以
  `version_incompatibility_rejection_rate=0.0` 失败；恢复后通过。
- 付费调用：CNY 0。
