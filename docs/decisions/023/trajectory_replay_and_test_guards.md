# 023：strict replay 与单元测试守卫

## 决定

- strict replay schema 升至 v3，并沿用既有 `AgentTrajectory`、`LLMCallTrace`、
  `ToolCallTrace` 与 `NodeTransitionTrace` 名称。
- 新录制为 LLM/tool/node trace 写入全局连续 `sequence` 与 `recorded_at`；LLM
  另记录 role+prompt 的 SHA-256 `normalized_key`。校验器拒绝版本、入口字段、
  artifact、顺序、时间戳或精确 prompt key 不一致的轨迹。
- schema 校验保留原有 required-call cache-miss 语义：缺少调用时仍返回 cache miss，
  不伪造响应。
- unit package 安装 socket connect fail-closed 守卫，默认只放行 localhost；真实调用
  必须显式用 `@allow_network` 标识。

## 未改变的边界

未实现 strategy 宽松匹配；未录制或补写任何真实 LLM 轨迹；默认 trajectory flag
仍关闭。合成 fixture 在路径、文件名和元数据中均标为 synthetic/fake，不能作为真实
验证证据。
