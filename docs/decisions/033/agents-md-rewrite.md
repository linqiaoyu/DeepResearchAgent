# 033 AGENTS.md 重写与默认值防漂移

## 结果

`AGENTS.md` 从 266 行改为 149 行；当前 diff 为 147 insertions / 264 deletions。
031 审计批准的六项建议全部实施。新文件只保留跨轮、能追溯到事故或明确风险的规则；
项目版本、历史路线、已实现清单和手抄默认值不再混进规范。

## 031 六项建议的落地

| 建议 | 新规则位置 | 事故依据 |
|---|---|---|
| 合并范围/现实/停止冲突 | 第 1–2 节 | 028 因“只执行明确事项”与“冲突即停”没有修 disclosure 断路 |
| 付费授权与预登记分离 | 第 3 节 | 022/023/025 把预登记误作二次审批，真实轨迹连续未执行 |
| 区分 benchmark 与 characterization snapshot | 第 5 节 | 027 合法 default flip 需要更新 snapshot，旧“冻结”措辞阻塞合理变化 |
| 本地全门禁无条件 | 第 6 节 | 027 仅跑 36 个子集，未做完整回归 |
| 固化新实验定义 | 第 5 节 | 030 修第三处断路后没有新实验，无法证明修复生效 |
| 默认值机械生成 | 第 8 节、CI 和单测 | 027 已把 dynamic capability 翻为 true，旧 AGENTS 仍写 false |

## 保留且未削弱的保护

- 密钥只从环境或未追踪 `.env` 读取，禁止进入日志、报告、轨迹、提交或终端输出；依据
  是 025/026 真实预检已证明凭据路径进入执行面。
- 无当轮授权禁止外部写、push、merge、force、amend、rebase、删分支；依据是不可逆
  远端和历史风险。
- 禁止弱化断言、删测、跳测、偷改题目/真值/判分；031 已证明测试真实性发现了真实
  长数字损坏。
- Golden/评测语料 immutable/versioned；只把 `tests/golden_output` 明确为可归因更新的
  characterization snapshot，没有放宽冻结 benchmark。
- Provider 必须留在工具/Agent 边界，外部调用必须有 timeout/retry/budget/degradation；
  026–031 的 CNINFO、AKShare、Tavily 事故都需要这个边界。
- 代码改动后无条件全量验证；push/merge 是否授权不再影响本地 gate。

## 删除或收缩的内容

| 删除/收缩 | 理由 |
|---|---|
| 005–020 的实现史、019 STOP/APBEC 明细、017–019 路线正文 | 应保存在 `docs/decisions/`，不是永久执行规范；历史正文造成规则和状态混杂 |
| Python/依赖的手抄版本清单和历史命令大全 | `pyproject.toml`、CI 和源码才是事实源；原文已经自相矛盾 |
| “只执行提示词逐字列出事项”和“仓库现实冲突即停” | 028 的直接停摆原因；替换为 in-scope 最小完整修复 |
| 所有断言/契约失败都整项交 PM | 曾让独立阶段被 STOP 连坐；现在只阻塞依赖后继，硬边界仍停 |
| 019 专属付费顺序和整轮成功判据 | 已是历史卡约束，继续常驻会误导后续实验 |
| 手写 20+ 开关默认值 | 已发生 dynamic 默认漂移；改为脚本从 `Settings` 和 manifest 分类生成 |
| 冗长 Review Gates/Scope Guardrails 的状态叙述 | 不是可执行跨轮规则；其中有效的 provider、测试、Evidence 原则已并入对应章节 |

## 防漂移机制

`scripts/sync_agents_settings.py` 从 `Settings` 的 bool 类型字段发现环境开关，再与 manifest
三分类合并，生成 `AGENTS.md` 表与 `.env.example` 块，并校验 README 的显式默认声明。
动态能力规则 JSON 也直接从 `Settings` 生成，避免示例环境再次丢失 disclosure/event
通道。未知 bool、缺分类、缺 env loader、手改生成块或 CI 不执行 `--check` 都会失败。
当前机械表有 21 个 flag，其中：

- `DYNAMIC_CAPABILITY_ENABLED=true`；
- `PROCEDURAL_MEMORY_ENABLED=false`，因为 033 连跑只读到一条策略但采用数为零；
- `SEMANTIC_JUDGE_ENABLED=false`，真实 judge 仍是显式付费实验。

恢复态原始结果：`Settings defaults check passed for AGENTS.md, .env.example, and README.md:
21 flags`，专门的默认值文档测试 10 项通过。
移除/变异验证保存于 `_collab/033/removal_validation/00_...` 至 `04_...`：分别覆盖一次
命令构造错误及修正、dataclass default 漂移、loader default 漂移、CI 命令删除和恢复态；
`22_...` 另证明删除动态规则生成行会立刻让 `.env.example` 校验失败。最终又补做三项：
`25_...` 把 README 的 dynamic 默认值改错后该检查失败；`26_...` 删除 semantic judge 的
manifest 分类后集合检查失败；`27_...` 让 loader 忽略 semantic judge 环境覆盖后覆盖测试
失败。当前恢复态是 21 flags / 10 tests；旧 `04_...` 里的 20/6 只保留为历史序列，不能
代表最终状态。

## 仍然存在的校验边界

- 自动同步覆盖 21 个 bool 和动态 capability rules JSON，不覆盖所有非布尔 Settings。
- README 扫描只识别精确的 `NAME=true|false` 声明；自由文本同义表述可能逃逸。
- CI 单测只检查命令字符串存在，注释也可能误通过；真实 workflow 当前确实有可执行 step，
  但后续应把 YAML step 结构纳入解析校验。
- loader 默认一致性由单测保证，不是同步脚本单独完成；因此 CI 必须同时跑全套测试。

## 规则收缩的补充说明

旧的“additive 默认翻转与 golden 必须组成连续两 commit 原子对”被收缩为“改默认与对应
characterization 同一任务内完成并单独说明”。原因是连续 commit 形状本身不能防止行为
错误，而且会人为规定开发历史；真正要保护的是可归因 diff 和完成后的全量 gate。旧文中
“整卡失败标签/生产代码行数上界不存在”、产品 Agent 不等同 Codex 角色、Review Gate
状态和核心能力优先级也被删除：前两项是历史争议澄清而非持续执行动作，后两项是产品
状态/路线，应归档在 decisions 与 roadmap。生产化自检没有消失，改为报告中的“demo-only
边界与已知限制”责任，而不是复制固定问题清单。

## 结构参考边界

OpenAI Agents SDK 与 Google ADK 的 AGENTS 文件只用于观察章节次序和入口边界的表达方式。
新规则的判断依据全部来自本仓库事故/风险；未复制两者规则文本。许可证与来源另见
`open-source-review.md`。
