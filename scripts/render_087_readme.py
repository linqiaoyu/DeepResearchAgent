"""Render the 087 README from the final package and registered A/B outcomes."""

from __future__ import annotations

import json
from pathlib import Path

from deepresearch_agent.provenance import FLAG_CLASSIFICATIONS, settings_flag_snapshot
from deepresearch_agent.settings import Settings


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts" / "087" / "live-nio-zh"
RESULTS = ROOT / "_collab" / "087" / "ab" / "results.json"
README = ROOT / "README.md"


def render() -> str:
    report = (PACKAGE / "report.md").read_text(encoding="utf-8").rstrip()
    results = {
        item["capability"]: item["decision"]
        for item in json.loads(RESULTS.read_text(encoding="utf-8"))["pairs"]
    }
    flags = settings_flag_snapshot(
        Settings(storage_path=Path("research.db")),
        include_disabled_experimental=True,
    )
    rows = []
    for flag in sorted(FLAG_CLASSIFICATIONS):
        capability = flag.removesuffix("_ENABLED")
        state = "on" if flags[flag] else "off"
        decision = results.get(capability, "not tested in 087 A/B")
        rows.append(f"| {flag} | {state} | {decision} |")
    return f'''# DeepResearchAgent

把投研结论带回可核对的来源，而不是交付一段无法复查的文字。

## 你会拿到什么

下面内容逐字来自 `artifacts/087/live-nio-zh/report.md`。

<!-- BEGIN 087 EMBEDDED REPORT -->
{report}
<!-- END 087 EMBEDDED REPORT -->

## 三分钟跑起来

```bash
python3 -m venv .venv
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pip install -e ".[dev]"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py
```

默认路径使用 deterministic fixture，不需要付费 provider 或 API key。

## 凭什么信它

报告把数值、对应 Evidence、引用闭合和成本账本放在同一个研究包；strict replay 用于复现已记录的轨迹，而不替代产物正确性检查。最终 NIO 包的数字、脚注和 provider 身份均由独立探针复核。

## 架构与边界

工作流由 Planner、Researcher、Extractor、Critic、Reporter 与 Evaluator 组成；研究子问题通过 LangGraph `Send()` 并行 fan-out。NodeContract、DecisionGate 与显式 DomainPack 约束边界。金融是唯一真实领域实现，不能据此宣称 harness 已通用可用。

## 25 个能力的实测状态

| Flag | Default | 087 outcome |
| --- | --- | --- |
{chr(10).join(rows)}

`promoted` 表示真实单开关 A/B 触发至少一项报告形态改善且没有形态劣化；`kept_off` 表示没有满足该规则。未测试项保持原默认值，不把“已接线”写成质量结论。

## 可审计性怎么实现的

每次运行保留 report、structured output、Evidence、manifest、ledger 与审计包。脚注映射不依赖 Evidence 当前顺序；外部工具经过超时、重试、预算与显式降级边界。

## 门禁与回归

唯一完整本地入口是 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/gate.py`。它覆盖 Settings 文档同步、领域边界、Ruff、prompt drift、完整单元测试、确定性 demo/eval smoke 与受跟踪文件不变检查。

## 它不做什么

- 不构成投资建议；分析师仍负责问题定义、来源许可、材料性、预测审批、发布和最终投资判断。
- 不把 strict replay 当成事实正确性的证明。
- 不在默认 CI、demo 或完整单测中要求付费 key。
- 不把当前金融领域 SUT 的验证外推为通用 domain-pack 能力。
'''


def main() -> None:
    README.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
