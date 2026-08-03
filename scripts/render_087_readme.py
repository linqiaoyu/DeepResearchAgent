"""Render the 087 README from the final package and registered A/B outcomes."""

from __future__ import annotations

import json
from pathlib import Path

from deepresearch_agent.provenance import FLAG_CLASSIFICATIONS, settings_flag_snapshot
from deepresearch_agent.settings import Settings
from deepresearch_agent.workflow.contracts import workflow_contract_graph


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts" / "087" / "live-nio-zh"
RESULTS = ROOT / "_collab" / "087" / "ab" / "results.json"
README = ROOT / "README.md"


def render() -> str:
    report = (PACKAGE / "report.md").read_text(encoding="utf-8").rstrip()
    results = _results_by_capability()
    flags = settings_flag_snapshot(
        Settings(storage_path=Path("research.db")),
        include_disabled_experimental=True,
    )
    rows: list[str] = []
    for flag in sorted(FLAG_CLASSIFICATIONS):
        capability = flag.removesuffix("_ENABLED")
        state = "on" if flags[flag] else "off"
        result = results.get(capability)
        if result is None:
            evidence = "not measured: single-report outcome is not the right test"
            decision = "kept default"
        else:
            evidence = f"reader lines {result['off']} → {result['on']}"
            decision = str(result["decision"])
        rows.append(f"| {flag} | {state} | {evidence} | {decision} |")
    manifest = json.loads(
        (PACKAGE / "audit_bundle" / "manifest.json").read_text(encoding="utf-8")
    )
    rag_cost = sum(
        float(json.loads(line)["cost_cny"])
        for line in (PACKAGE / "runtime" / "rag_ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    graph = workflow_contract_graph()
    node_count = len({node for edge in graph.edges for node in edge})
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

报告把数值、对应 Evidence、引用闭合和成本账本放在同一个研究包；strict replay 用于复现已记录的轨迹，而不替代产物正确性检查。最终 NIO 包的 workflow 成本为 CNY {float(manifest['cost_cny_total']):.8f}，RAG 成本为 CNY {rag_cost:.7f}；数字、脚注和 provider 身份均由独立探针复核。

<!-- 087-FACT workflow_cost={float(manifest['cost_cny_total']):.8f} rag_cost={rag_cost:.7f} -->

## 架构与边界

当前工作流的 {node_count} 个节点由 Planner、Researcher、Extractor、Critic、Reporter 与 Evaluator 组成；研究子问题通过 LangGraph `Send()` 并行 fan-out。NodeContract、DecisionGate 与显式 DomainPack 约束边界。金融是唯一真实领域实现，不能据此宣称 harness 已通用可用。

## 25 个能力的实测状态

| Flag | Default | Real A/B evidence | 087 outcome |
| --- | --- | --- | --- |
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
- `REFLECTION_ENABLED` 保持关闭：确定性信号和接口存在，但没有本轮策略采用增益证据。
- `CONTEXT_PACKER_ENABLED` 的默认开启只代表本轮单开关报告形态证据；它不等于所有主题的质量结论。`RESEARCH_LOOP_ENABLED`、`SKILL_PACKS_ENABLED` 与 `TRAJECTORY_RECORD_ENABLED` 保持关闭，因为本轮 A/B 未观察到严格增益。
- MCP 不提供任意文件读取或命令执行；外部工具仍经过统一的超时、重试、预算与降级契约。
- Docker/Compose 资产不是本机容器引擎构建证据；当前交付以项目虚拟环境的可复现 gate 为准。
'''


def _results_by_capability() -> dict[str, dict[str, object]]:
    try:
        from scripts.check_087_report_shape import measure
    except ModuleNotFoundError:
        from check_087_report_shape import measure

    payload = json.loads(RESULTS.read_text(encoding="utf-8"))
    result: dict[str, dict[str, object]] = {}
    for pair in payload["pairs"]:
        paths = [
            (RESULTS.parent / pair[key]).resolve()
            for key in ("off_package", "on_package")
        ]
        result[str(pair["capability"])] = {
            "decision": pair["decision"],
            "off": measure((paths[0] / "report.md").read_text(encoding="utf-8"))["reader_visible_lines"],
            "on": measure((paths[1] / "report.md").read_text(encoding="utf-8"))["reader_visible_lines"],
        }
    return result


def main() -> None:
    README.write_text(render(), encoding="utf-8")


if __name__ == "__main__":
    main()
