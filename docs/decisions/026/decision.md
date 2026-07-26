# 026 决策记录：配置校验与 `.env` 凭据来源一致

## 已证实事实

- 项目根目录 `.env` 已有非空 `DEEPSEEK_API_KEY`，但此前 `DeepResearchEngine` 构造时的 fail-fast 校验只读取进程环境，造成真实 LLM 运行在 provider 调用前误报缺少该变量。
- `LLMClient` 原本会读取同一 `.env`，但发生在 fail-fast 校验之后；两者的加载顺序不一致是 025 未完成真实运行的直接原因。
- 配置校验现在在正常运行时读取项目 `.env`，并由 shell 环境变量覆盖同名键；显式注入的 `environ` 仍完全隔离，不读取 `.env`。
- 已通过单元测试及不导出密钥的 LLM 模式引擎构造验证；未打印或提交任何密钥内容。

## 未证实 / 未交付

- 本次仅验证引擎构造通过，不构成真实 provider 调用、真实端到端研究或 trajectory replay 成立的证据。

## 契约变更

配置校验的凭据解析顺序变更为：项目 `.env` 回退，shell 环境变量优先。变更理由是使 fail-fast 校验与既有 `LLMClient` 使用同一凭据来源，避免凭据存在但在 LLM 客户端创建前被错误拦截。

## 026 后续实证补记

- 默认 capability selector 现在可见并选择 `disclosure_source`；默认固定 workflow 仍不会调用它，避免既有冻结 snapshot 的外网副作用。
- 当前结构化数据默认是 fixture；AKShare live 实测无法连接，不能称为生产主数据源。
- 真实年报窗口中表格文本可读，但单点 LLM 漏读已进入窗口的毛利率；固定一次窗口不能被表述为充分。
- 真实完整运行未形成 trajectory，因此 021 阶段 4 仍未关闭。
