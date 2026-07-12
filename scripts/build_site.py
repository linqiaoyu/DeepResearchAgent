from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "site" / "dist"
SHOWCASE_PATH = ROOT / "data" / "demo" / "g3_showcase.json"
GEN3_PATH = ROOT / "data" / "golden_set" / "v1" / "results" / "gen3_judge1.json"
EVAL_DOC_PATH = ROOT / "docs" / "evaluation.md"


def main() -> None:
    showcase = _read_json(SHOWCASE_PATH)
    gen3 = _read_json(GEN3_PATH)
    evaluation_doc = EVAL_DOC_PATH.read_text(encoding="utf-8")
    validation = _validate_numbers(showcase, gen3, evaluation_doc)
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "assets").mkdir(parents=True)
    (DIST / "reports").mkdir(parents=True)
    _write_css(DIST / "assets" / "styles.css")
    reports = showcase["reports"]
    _write_page("index.html", _home_page(showcase, validation))
    _write_page("methodology.html", _methodology_page(showcase, validation))
    _write_page("reproduce.html", _reproduce_page())
    _write_page("reports/index.html", _reports_index(reports))
    for report in reports:
        _write_page(f"reports/{report['id']}.html", _report_page(report))
    manifest = {
        "generated_from": {
            "showcase": str(SHOWCASE_PATH.relative_to(ROOT)),
            "gen3": str(GEN3_PATH.relative_to(ROOT)),
            "evaluation_doc": str(EVAL_DOC_PATH.relative_to(ROOT)),
        },
        "files": sorted(str(path.relative_to(DIST)) for path in DIST.rglob("*") if path.is_file()),
        "validation": validation,
    }
    (DIST / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"built {DIST}")
    print(f"files {len(manifest['files']) + 1}")
    print("validation ok")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_numbers(showcase: dict[str, Any], gen3: dict[str, Any], doc: str) -> dict[str, Any]:
    if showcase["summary"] != gen3["summary"]:
        raise SystemExit("data/demo/g3_showcase.json summary differs from gen3_judge1.json summary")
    summary = gen3["summary"]
    required_values = {
        "avg_weighted_score": _fmt4(summary["avg_weighted_score"]),
        "avg_fact_coverage": _fmt4(summary["avg_fact_coverage"]),
        "avg_fact_accuracy": _fmt4(summary["avg_fact_accuracy"]),
        "avg_citation_support": _fmt4(summary["avg_citation_support"]),
        "avg_synthesis_balance": _fmt4(summary["avg_synthesis_balance"]),
        "avg_citation_support_rate": _fmt4(summary["avg_citation_support_rate"]),
        "avg_citation_resolution_rate": _fmt4(summary["avg_citation_resolution_rate"]),
        "avg_citation_repair_retry_rate": _fmt4(summary["avg_citation_repair_retry_rate"]),
        "avg_uncited_claim_rate": _fmt4(summary["avg_uncited_claim_rate"]),
    }
    missing = [value for value in required_values.values() if value not in doc]
    if missing:
        raise SystemExit(f"docs/evaluation.md missing G3 values: {missing}")
    decomposition = _required_match(r"(\d\.\d{4} \+ \d\.\d{4} - \d\.\d{4} = \d\.\d{4})", doc)
    weights = {
        "fact_coverage": _required_match(r"\| `fact_coverage` \| ([0-9.]+) \|", doc, group=1),
        "fact_accuracy": _required_match(r"\| `fact_accuracy` \| ([0-9.]+) \|", doc, group=1),
        "citation_support": _required_match(r"\| `citation_support` \| ([0-9.]+) \|", doc, group=1),
        "synthesis_balance": _required_match(r"\| `synthesis_balance` \| ([0-9.]+) \|", doc, group=1),
    }
    sequence = {
        "avg_weighted_score": _sequence_row("avg weighted score", doc),
        "avg_citation_support": _sequence_row("avg citation support", doc),
        "avg_citation_resolution_rate": _sequence_row("avg citation resolution rate", doc),
    }
    noise = {
        "judge_retest_band": _required_match(r"±0\.01", doc),
        "observed_retest_noise": _required_match(r"±0\.004", doc),
        "generation_standard_error": _required_match(r"0\.037", doc),
        "per_question_swing": _required_match(r"±0\.4", doc),
    }
    false_premise = summary["false_premise"]
    if false_premise.get("passed") != 2 or false_premise.get("failed") != 0:
        raise SystemExit("Gen3 false-premise summary is not 2/2")
    return {
        "summary_values": required_values,
        "decomposition": decomposition,
        "weights": weights,
        "sequence": sequence,
        "noise": noise,
        "false_premise": false_premise,
    }


def _required_match(pattern: str, text: str, *, group: int = 0) -> str:
    match = re.search(pattern, text)
    if not match:
        raise SystemExit(f"docs/evaluation.md missing pattern: {pattern}")
    return match.group(group)


def _sequence_row(metric: str, doc: str) -> dict[str, str]:
    pattern = rf"\| {re.escape(metric)} \| ([0-9.]+) \| ([0-9.]+) \| ([0-9.]+) \|"
    match = re.search(pattern, doc)
    if not match:
        raise SystemExit(f"docs/evaluation.md missing sequence row: {metric}")
    return {"g1": match.group(1), "g2": match.group(2), "g3": match.group(3)}


def _fmt4(value: float) -> str:
    return f"{float(value):.4f}"


def _write_page(relative_path: str, body: str) -> None:
    path = DIST / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _layout(title: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)} · DeepResearchAgent</title>
  <link rel="stylesheet" href="{_asset_prefix(title)}assets/styles.css">
</head>
<body>
  <header class="site-header">
    <a class="brand" href="{_asset_prefix(title)}index.html">DeepResearchAgent</a>
    <nav>
      <a href="{_asset_prefix(title)}reports/index.html">报告</a>
      <a href="{_asset_prefix(title)}methodology.html">方法论</a>
      <a href="{_asset_prefix(title)}reproduce.html">复现</a>
      <a href="https://github.com/linqiaoyu/DeepResearchAgent">GitHub</a>
    </nav>
  </header>
  <main>{content}</main>
</body>
</html>
"""


def _asset_prefix(title: str) -> str:
    return "../" if title.startswith("报告 ") else ""


def _home_page(showcase: dict[str, Any], validation: dict[str, Any]) -> str:
    summary = showcase["summary"]
    cards = [
        ("Golden cases", summary["cases"]),
        ("G3 composite", _fmt4(summary["avg_weighted_score"])),
        ("Citation support", _fmt4(summary["avg_citation_support"])),
        ("Resolution", _fmt4(summary["avg_citation_resolution_rate"])),
        ("False premise", f"{summary['false_premise']['passed']}/2"),
    ]
    return _layout(
        "首页",
        f"""
<section class="hero">
  <p class="eyebrow">金融投研深度研究 Agent</p>
  <h1>从证据、引用、批判循环到 Golden Set 评测的可复现实验系统</h1>
  <p>公开触达形态为纯静态站；可部署资产保留异步重跑队列、日消耗护栏与 owner-token live 层。</p>
</section>
<section class="cards">{''.join(_card(label, value) for label, value in cards)}</section>
<section>
  <h2>执行图</h2>
  <div class="flow">
    <span>Planner</span><span>Researcher fan-out</span><span>Extractor</span><span>Critic retry</span><span>Reporter</span><span>Evaluator</span>
  </div>
</section>
<section>
  <h2>评测口径</h2>
  <p>判官效应分解：<code>{validation['decomposition']}</code>。Judge 复测噪声 {validation['noise']['judge_retest_band']}，跨代际标准误 {validation['noise']['generation_standard_error']}。</p>
  <p><a class="button" href="reports/index.html">查看精选 G3 报告</a></p>
</section>
""",
    )


def _methodology_page(showcase: dict[str, Any], validation: dict[str, Any]) -> str:
    summary = showcase["summary"]
    weights = validation["weights"]
    rows = [
        ("fact_coverage", weights["fact_coverage"], _fmt4(summary["avg_fact_coverage"])),
        ("fact_accuracy", weights["fact_accuracy"], _fmt4(summary["avg_fact_accuracy"])),
        ("citation_support", weights["citation_support"], _fmt4(summary["avg_citation_support"])),
        ("synthesis_balance", weights["synthesis_balance"], _fmt4(summary["avg_synthesis_balance"])),
    ]
    sequence = validation["sequence"]
    return _layout(
        "方法论",
        f"""
<section class="page-title">
  <h1>Golden Set v1 方法论</h1>
  <p>Judge 与 citation_support 均锁定 qwen3.7-plus；检索为 frozen-corpus replay。</p>
</section>
<section>
  <h2>四维量规</h2>
  <table><thead><tr><th>维度</th><th>权重</th><th>G3 均值</th></tr></thead><tbody>
    {''.join(f'<tr><td>{name}</td><td>{weight}</td><td>{value}</td></tr>' for name, weight, value in rows)}
  </tbody></table>
</section>
<section>
  <h2>判官效应与噪声带</h2>
  <p><code>{validation['decomposition']}</code></p>
  <ul>
    <li>Judge 复测噪声：{validation['noise']['judge_retest_band']}，实测 {validation['noise']['observed_retest_noise']}</li>
    <li>跨代际生成标准误：{validation['noise']['generation_standard_error']}</li>
    <li>逐题波动可达：{validation['noise']['per_question_swing']}</li>
  </ul>
</section>
<section>
  <h2>三代际序列</h2>
  <table><thead><tr><th>指标</th><th>G1 rejudge</th><th>G2 backfill</th><th>G3 repair retry</th></tr></thead><tbody>
    <tr><td>avg weighted score</td><td>{sequence['avg_weighted_score']['g1']}</td><td>{sequence['avg_weighted_score']['g2']}</td><td>{sequence['avg_weighted_score']['g3']}</td></tr>
    <tr><td>avg citation support</td><td>{sequence['avg_citation_support']['g1']}</td><td>{sequence['avg_citation_support']['g2']}</td><td>{sequence['avg_citation_support']['g3']}</td></tr>
    <tr><td>avg citation resolution</td><td>{sequence['avg_citation_resolution_rate']['g1']}</td><td>{sequence['avg_citation_resolution_rate']['g2']}</td><td>{sequence['avg_citation_resolution_rate']['g3']}</td></tr>
  </tbody></table>
  <p>假前提反驳：{summary['false_premise']['passed']}/2。</p>
</section>
""",
    )


def _reproduce_page() -> str:
    return _layout(
        "复现",
        """
<section class="page-title">
  <h1>复现与可部署资产</h1>
  <p>静态站不依赖后端；仓库仍保留可部署的 API/UI 演示资产。</p>
</section>
<section>
  <h2>Docker Compose 三步</h2>
  <ol>
    <li>复制仓库并创建只存服务器侧的 <code>.env</code>。</li>
    <li>运行 <code>docker compose up -d --build</code>。</li>
    <li>访问 <code>/demo</code> 与 Streamlit UI。</li>
  </ol>
</section>
<section>
  <h2>可部署资产</h2>
  <ul>
    <li>异步 Golden rerun 作业队列：并发 1，队列上限 3。</li>
    <li>持久化日消耗护栏：默认 5 元人民币。</li>
    <li>Owner live 层：需要 <code>X-Demo-Owner-Token</code>。</li>
  </ul>
</section>
""",
    )


def _reports_index(reports: list[dict[str, Any]]) -> str:
    items = "".join(
        f"""<article class="report-card">
  <h2><a href="{report['id']}.html">{html.escape(report['id'])}: {html.escape(report['topic'])}</a></h2>
  <p>{html.escape(report['type'])} · {html.escape(report['difficulty'])}</p>
  <p>Weighted score: {_fmt4(report['metrics']['weighted_score'])}</p>
</article>"""
        for report in reports
    )
    return _layout("报告 索引", f"<section class='page-title'><h1>精选 G3 报告</h1></section>{items}")


def _report_page(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    cards = [
        ("Weighted", _fmt4(metrics["weighted_score"])),
        ("Support rate", _fmt4(metrics["citation_support_rate"])),
        ("Resolution", _fmt4(metrics["citation_resolution_rate"])),
        ("Repair retry", _fmt4(metrics["citation_repair_retry_rate"])),
        ("Uncited", _fmt4(metrics["uncited_claim_rate"])),
    ]
    content = f"""
<section class="page-title">
  <p class="eyebrow">{html.escape(report['type'])} · {html.escape(report['difficulty'])}</p>
  <h1>{html.escape(report['id'])}</h1>
</section>
<section class="cards">{''.join(_card(label, value) for label, value in cards)}</section>
<article class="report-body">{_markdown_to_html(report['report_markdown'])}</article>
"""
    return _layout(f"报告 {report['id']}", content)


def _markdown_to_html(markdown: str) -> str:
    body_lines: list[str] = []
    refs: list[str] = []
    in_list = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            continue
        ref_match = re.match(r"\[\^(\d+)\]:\s*(.*)", line)
        if ref_match:
            refs.append(
                f'<li id="ref-{ref_match.group(1)}">{_inline(ref_match.group(2))}</li>'
            )
            continue
        if line.startswith("### "):
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            body_lines.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            body_lines.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            body_lines.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("- "):
            if not in_list:
                body_lines.append("<ul>")
                in_list = True
            body_lines.append(f"<li>{_inline(line[2:])}</li>")
        else:
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            body_lines.append(f"<p>{_inline(line)}</p>")
    if in_list:
        body_lines.append("</ul>")
    if refs:
        body_lines.append("<h2>参考来源</h2><ol class='references'>" + "".join(refs) + "</ol>")
    return "\n".join(body_lines)


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(
        r"\[\^(\d+)\]",
        lambda match: f'<a class="citation" href="#ref-{match.group(1)}">[{match.group(1)}]</a>',
        escaped,
    )
    escaped = re.sub(
        r"(https?://[^\s)]+)",
        lambda match: f'<a href="{match.group(1)}">{match.group(1)}</a>',
        escaped,
    )
    return escaped


def _card(label: str, value: Any) -> str:
    return f"<div class='card'><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></div>"


def _write_css(path: Path) -> None:
    path.write_text(
        """
:root { color-scheme: light; --ink:#17202a; --muted:#5d6d7e; --line:#d7dee8; --bg:#f7f9fb; --accent:#14532d; --panel:#ffffff; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); background: var(--bg); line-height: 1.65; }
a { color: #0f5f8f; }
.site-header { position: sticky; top: 0; z-index: 5; display: flex; justify-content: space-between; align-items: center; gap: 24px; padding: 14px 28px; border-bottom: 1px solid var(--line); background: rgba(255,255,255,.94); }
.brand { font-weight: 800; text-decoration: none; color: var(--ink); }
nav { display: flex; gap: 16px; flex-wrap: wrap; }
nav a { text-decoration: none; color: var(--muted); font-weight: 650; }
main { max-width: 1120px; margin: 0 auto; padding: 36px 24px 80px; }
.hero { padding: 42px 0 26px; }
.hero h1, .page-title h1 { max-width: 920px; font-size: clamp(2rem, 5vw, 4.5rem); line-height: 1.05; margin: 0 0 18px; }
.hero p, .page-title p { max-width: 780px; color: var(--muted); font-size: 1.08rem; }
.eyebrow { text-transform: uppercase; letter-spacing: .08em; font-weight: 800; color: var(--accent); font-size: .78rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 22px 0 34px; }
.card, .report-card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; }
.card span { color: var(--muted); display: block; font-size: .88rem; }
.card strong { display: block; font-size: 1.55rem; margin-top: 4px; }
.flow { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 10px; }
.flow span { border: 1px solid var(--line); border-radius: 999px; padding: 10px 12px; text-align: center; background: var(--panel); font-weight: 700; }
section, article { margin: 0 0 38px; }
table { border-collapse: collapse; width: 100%; background: var(--panel); }
th, td { border: 1px solid var(--line); padding: 10px 12px; text-align: left; vertical-align: top; }
th { background: #edf3f8; }
.button { display: inline-block; padding: 10px 14px; background: var(--accent); color: #fff; border-radius: 6px; text-decoration: none; font-weight: 750; }
.report-body { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 20px; overflow-wrap: anywhere; }
.report-body h1 { font-size: 1.8rem; line-height: 1.2; }
.citation { font-weight: 800; text-decoration: none; }
.references { padding-left: 20px; }
code { background: #edf3f8; padding: 2px 5px; border-radius: 4px; }
@media (max-width: 720px) { .site-header { align-items: flex-start; flex-direction: column; } main { padding: 24px 16px 60px; } }
""".strip()
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
