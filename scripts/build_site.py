"""Build the static showcase exclusively from Golden v1.1 release assets."""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from deepresearch_agent.provenance import RunManifest  # noqa: E402
from deepresearch_agent.research_snapshot import (  # noqa: E402
    build_demo_followup,
    build_research_snapshot,
    diff_research_snapshots,
)
from deepresearch_agent.schemas import Evidence, ResearchState  # noqa: E402
from deepresearch_agent.settings import Settings  # noqa: E402
from deepresearch_agent.structured_output import build_structured_output  # noqa: E402

DIST = ROOT / "site" / "dist"
SHOWCASE_PATH = ROOT / "data" / "demo" / "g3_showcase.json"
G3_PATH = ROOT / "data" / "golden_set" / "v1" / "results" / "g3_judge_v11.json"
CITATION_PATH = ROOT / "data" / "golden_set" / "v1" / "results" / "g3_citation_support_3s.json"
AUDIT_PATH = ROOT / "data" / "golden_set" / "v1" / "audit_v11.json"
FREEZE_PATH = ROOT / "data" / "golden_set" / "v1" / "freeze.md"
BUSINESS_FIXTURE_PATH = ROOT / "tests" / "golden_output" / "wealth_research.json"
FORBIDDEN_V10_NUMBERS = ("0.7803", "0.7999")
HISTORICAL_JUDGE_DECOMPOSITION = "0.6134 + 0.1865 - 0.0585 = 0.7414"


def main() -> None:
    showcase = _read_json(SHOWCASE_PATH)
    g3 = _read_json(G3_PATH)
    citation = _read_json(CITATION_PATH)
    audit = _read_json(AUDIT_PATH)
    freeze = FREEZE_PATH.read_text(encoding="utf-8")
    validation = _validate_release_assets(showcase, g3, citation, audit, freeze)
    business = _business_scenario_from_fixture()
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "assets").mkdir(parents=True)
    (DIST / "reports").mkdir(parents=True)
    _write_css(DIST / "assets" / "styles.css")
    reports = showcase["reports"]
    _write_page("index.html", _home_page(showcase, validation))
    _write_page("methodology.html", _methodology_page(showcase, validation))
    _write_page("reproduce.html", _reproduce_page())
    _write_page("scenarios.html", _business_scenario_page(business))
    _write_page(
        "business-report.html",
        _business_report_page(business),
    )
    _write_page("reports/index.html", _reports_index(reports))
    for report in reports:
        _write_page(f"reports/{report['id']}.html", _report_page(report, validation["retrieval_as_of"]))
    _assert_site(DIST, business)
    manifest = {
        "generated_from": {
            "showcase": str(SHOWCASE_PATH.relative_to(ROOT)),
            "g3_judge": str(G3_PATH.relative_to(ROOT)),
            "citation_support": str(CITATION_PATH.relative_to(ROOT)),
            "audit": str(AUDIT_PATH.relative_to(ROOT)),
            "freeze": str(FREEZE_PATH.relative_to(ROOT)),
            "business_fixture": str(BUSINESS_FIXTURE_PATH.relative_to(ROOT)),
        },
        "validation": validation,
        "files": sorted(str(path.relative_to(DIST)) for path in DIST.rglob("*") if path.is_file()),
    }
    (DIST / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"built {DIST}")
    print(f"files {len(manifest['files']) + 1}")
    print("validation ok")


def _validate_release_assets(
    showcase: dict[str, Any],
    g3: dict[str, Any],
    citation: dict[str, Any],
    audit: dict[str, Any],
    freeze: str,
) -> dict[str, Any]:
    retrieval_as_of = _required_match(r"^retrieval_corpus_as_of:\s*(\d{4}-\d{2}-\d{2})$", freeze)
    appendix_captured = _required_match(r"^gold_appendix_captured:\s*(\d{4}-\d{2}-\d{2})$", freeze)
    if retrieval_as_of != "2026-07-09":
        raise SystemExit(f"unexpected retrieval corpus clock: {retrieval_as_of}")
    if showcase.get("version") != "g3_showcase_v1.1" or showcase.get("as_of") != retrieval_as_of:
        raise SystemExit("showcase must be synchronized to Golden v1.1 and the freeze retrieval clock")
    expected_summary = dict(g3["summary"])
    expected_summary["avg_citation_support_rate"] = citation["summary"]["avg_citation_support_rate"]
    if showcase.get("summary") != expected_summary:
        raise SystemExit("showcase summary differs from v1.1 G3 release assets")
    if citation.get("verifier", {}).get("samples_per_question") != 3:
        raise SystemExit("citation_support release asset is not a three-sample verifier")
    if audit.get("summary", {}).get("counts") != {"PASS": 76, "DEFECT": 0, "UNCERTAIN": 3}:
        raise SystemExit("audit_v11 does not meet the frozen 76/0/3 gate")
    g3_by_id = {item["id"]: item for item in g3["results"]}
    citation_by_id = {item["id"]: item for item in citation["results"]}
    for report in showcase["reports"]:
        qid = report["id"]
        release = g3_by_id.get(qid)
        support = citation_by_id.get(qid)
        if not release or not support:
            raise SystemExit(f"showcase report {qid} is absent from release results")
        expected_metrics = {
            "weighted_score": release["judge"]["median"]["weighted_score"],
            "citation_support_rate": support["support_rate"],
            "citation_resolution_rate": release["mechanical"]["citation_resolution_rate"],
            "citation_repair_retry_rate": release["mechanical"]["citation_repair_retry_rate"],
            "uncited_claim_rate": release["mechanical"]["uncited_claim_rate"],
        }
        if report.get("metrics") != expected_metrics:
            raise SystemExit(f"showcase report {qid} metrics differ from v1.1 release assets")
    return {
        "retrieval_as_of": retrieval_as_of,
        "gold_appendix_captured": appendix_captured,
        "audit_counts": audit["summary"]["counts"],
        "citation_samples": 3,
    }


def _assert_site(
    dist: Path,
    business: dict[str, Any] | None = None,
) -> None:
    pages = sorted((dist / "reports").glob("Q*.html"))
    if not pages:
        raise SystemExit("site has no report pages")
    all_text = "\n".join(path.read_text(encoding="utf-8") for path in dist.rglob("*.html"))
    methodology = (dist / "methodology.html").read_text(encoding="utf-8")
    other_pages = all_text.replace(HISTORICAL_JUDGE_DECOMPOSITION, "")
    forbidden = [
        value
        for value in ("1970-01-01", *FORBIDDEN_V10_NUMBERS, "0.7414")
        if value in other_pages
    ]
    if forbidden:
        raise SystemExit(f"site contains forbidden legacy values: {forbidden}")
    if methodology.count(HISTORICAL_JUDGE_DECOMPOSITION) != 1:
        raise SystemExit("methodology must contain exactly one historical judge decomposition")
    for page in pages:
        text = page.read_text(encoding="utf-8")
        if text.count("<h2>参考来源</h2>") != 1:
            raise SystemExit(f"{page.name} must contain exactly one references heading")
        anchors = set(re.findall(r'id="(ref-\d+)"', text))
        links = re.findall(r'href="#(ref-\d+)"', text)
        if any(link not in anchors for link in links):
            raise SystemExit(f"{page.name} contains a citation anchor without a reference")
    q01 = (dist / "reports" / "Q01.html").read_text(encoding="utf-8")
    if q01.count("<li id=\"ref-") != 7:
        raise SystemExit("Q01 references must equal its seven unique URLs")
    if business is None:
        return
    scenario = (dist / "scenarios.html").read_text(encoding="utf-8")
    required = (
        "确定性 fixture 数据",
        "非真实客户使用记录",
        str(business["evidence_count"]),
        str(business["metric_count"]),
        str(len(business["diff"].changes)),
    )
    if any(value not in scenario for value in required):
        raise SystemExit("business scenario is not synchronized to fixture output")
    if business["missing_evidence_ids"]:
        raise SystemExit("business scenario audit closure is incomplete")
    change_types = {item.change_type for item in business["diff"].changes}
    if len(change_types) != 6:
        raise SystemExit("business scenario must demonstrate six change categories")


def _required_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise SystemExit(f"freeze metadata missing pattern: {pattern}")
    return match.group(1)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_page(relative_path: str, body: str) -> None:
    path = DIST / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _layout(title: str, content: str) -> str:
    prefix = "../" if title.startswith("报告 ") else ""
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · DeepResearchAgent</title><link rel="stylesheet" href="{prefix}assets/styles.css"></head>
<body><header class="site-header"><a class="brand" href="{prefix}index.html">DeepResearchAgent</a><nav>
<a href="{prefix}reports/index.html">报告</a><a href="{prefix}scenarios.html">业务场景</a><a href="{prefix}methodology.html">方法论</a><a href="{prefix}reproduce.html">复现</a>
<a href="https://github.com/linqiaoyu/DeepResearchAgent">GitHub</a></nav></header><main>{content}</main></body></html>"""


def _home_page(showcase: dict[str, Any], validation: dict[str, Any]) -> str:
    summary = showcase["summary"]
    cards = [
        ("G3 composite", _fmt4(summary["avg_weighted_score"])),
        ("Fact accuracy", _fmt4(summary["avg_fact_accuracy"])),
        ("Citation support (3s)", _fmt4(summary["avg_citation_support_rate"])),
        ("Resolution", _fmt4(summary["avg_citation_resolution_rate"])),
        ("False premise", f"{summary['false_premise']['passed']}/2"),
    ]
    return _layout(
        "首页",
        f"""<section class="hero"><p class="eyebrow">Golden v1.1 release</p><h1>证据驱动的金融投研深度研究 Agent</h1>
<p>G3 保存态以冻结检索语料回放评测；检索语料截至 {validation['retrieval_as_of']}。</p></section>
<section class="cards">{''.join(_card(label, value) for label, value in cards)}</section>
<section><h2>执行图</h2><div class="flow"><span>Planner</span><span>Researcher Send fan-out</span><span>Extractor</span><span>Critic 条件回流</span><span>Reporter</span><span>Judge</span></div></section>
<section><h2>发布控制</h2><p>四键审计：{validation['audit_counts']['PASS']} PASS、{validation['audit_counts']['DEFECT']} DEFECT、{validation['audit_counts']['UNCERTAIN']} 条 PM 注记 UNCERTAIN。citation_support 为每题 {validation['citation_samples']} 次、逐 claim 多数决。</p><p><a class="button" href="reports/index.html">查看 G3 报告</a></p></section>""",
    )


def _methodology_page(showcase: dict[str, Any], validation: dict[str, Any]) -> str:
    summary = showcase["summary"]
    rows = [("fact_coverage", "0.35", summary["avg_fact_coverage"]), ("fact_accuracy", "0.25", summary["avg_fact_accuracy"]), ("citation_support", "0.25", summary["avg_citation_support"]), ("synthesis_balance", "0.15", summary["avg_synthesis_balance"])]
    return _layout(
        "方法论",
        f"""<section class="page-title"><h1>Golden Set v1.1 方法论</h1><p>Judge 与 citation_support 均锁定 qwen3.7-plus；检索语料截至 {validation['retrieval_as_of']}，gold 附录采集于 {validation['gold_appendix_captured']}。</p></section>
<section><h2>四维量规</h2><table><thead><tr><th>维度</th><th>权重</th><th>G3 均值</th></tr></thead><tbody>{''.join(f'<tr><td>{key}</td><td>{weight}</td><td>{_fmt4(value)}</td></tr>' for key, weight, value in rows)}</tbody></table></section>
<section><h2>审计与引用验证</h2><p>四键写入闸覆盖实体、归一指标、报告期、口径/单位和数字摘录。v1.1 审计为 {validation['audit_counts']['PASS']}/0/{validation['audit_counts']['UNCERTAIN']}；citation_support 使用 {validation['citation_samples']} 采样逐 claim 多数决。</p></section>
<section><h2>判官效应分解（gold v1.0 历史测量）</h2><p><code>{HISTORICAL_JUDGE_DECOMPOSITION}</code></p></section>""",
    )


def _reproduce_page() -> str:
    return _layout("复现", """<section class="page-title"><h1>复现与可部署资产</h1><p>静态站不依赖后端；仓库保留 API/UI 演示资产。</p></section><section><h2>三步</h2><ol><li>复制仓库并配置服务器侧 .env。</li><li>运行 <code>docker compose up -d --build</code>。</li><li>访问 <code>/demo</code> 或 Streamlit UI。</li></ol></section>""")


def _business_scenario_from_fixture() -> dict[str, Any]:
    payload = _read_json(BUSINESS_FIXTURE_PATH)
    fixed_time = datetime(2026, 7, 9, tzinfo=timezone.utc)
    evidence = [
        Evidence(
            id=item["id"],
            research_id="fixture-business-scenario",
            sub_question_id=item["sub_question_id"],
            claim=item["claim"],
            claim_type=item["claim_type"],
            source_kind=item["source_kind"],
            source_url=item["source_url"],
            source_title=item["source_title"],
            source_pub_date=date.fromisoformat(item["source_pub_date"]),
            extract_text=item["extract_text"],
            confidence=item["confidence"],
            numeric_fields=item["numeric_fields"],
            extracted_at=fixed_time,
        )
        for item in payload["evidence"]
    ]
    state = ResearchState(
        topic=payload["topic"],
        evidence_store=evidence,
        final_report=payload["final_report"],
    )
    structured = build_structured_output(state)
    state.structured_output = structured
    manifest_payload = dict(payload["side_effects"]["manifest"])
    manifest_payload.update(
        {
            "run_id": "fixture-business-scenario",
            "started_at": fixed_time,
            "ended_at": fixed_time,
            "config_hash": "fixture-characterization",
        }
    )
    manifest = RunManifest.model_validate(manifest_payload)
    settings = Settings(
        storage_path=ROOT / "data" / "runtime" / "site-business.db",
        as_of=date(2026, 7, 9),
    )
    baseline = build_research_snapshot(
        state=state,
        settings=settings,
        manifest=manifest,
        as_of=date(2026, 7, 9),
    )
    followup = build_demo_followup(
        baseline,
        as_of=date(2026, 7, 24),
    )
    snapshot_diff = diff_research_snapshots(baseline, followup)
    available_ids = {item.id for item in evidence}
    cited_ids = {
        evidence_id
        for claim in payload["report_claims"]
        for evidence_id in claim["evidence_ids"]
    }
    return {
        "topic": payload["topic"],
        "report": payload["final_report"],
        "evidence_count": len(evidence),
        "report_claim_count": len(payload["report_claims"]),
        "cited_evidence_count": len(cited_ids),
        "missing_evidence_ids": sorted(cited_ids - available_ids),
        "structured": structured,
        "metric_count": len(structured.comparison_table.rows),
        "diff": snapshot_diff,
    }


def _business_scenario_page(business: dict[str, Any]) -> str:
    rows = business["structured"].comparison_table.rows[:6]
    metric_rows = "".join(
        "<tr>"
        f"<td>{html.escape(row.entity)}</td>"
        f"<td>{html.escape(row.normalized_metric)}</td>"
        f"<td>{html.escape(row.period or '未标注')}</td>"
        f"<td>{html.escape(row.scope)}</td>"
        f"<td>{row.value:g} {html.escape(row.unit)}</td>"
        f"<td>{html.escape(', '.join(row.evidence_ids))}</td>"
        "</tr>"
        for row in rows
    )
    change_labels = {
        "added_claim": "新增论点",
        "disappeared_claim": "消失论点",
        "numeric_change": "数值变化",
        "evidence_replacement": "证据更替",
        "confidence_change": "置信度变化",
        "scope_change": "口径变化",
    }
    changes = "".join(
        "<li>"
        f"<strong>{change_labels[item.change_type]}</strong>"
        f"<span>{html.escape(item.materiality)}</span>"
        f"<p>{html.escape(item.detail)}</p>"
        "</li>"
        for item in business["diff"].changes
    )
    return _layout(
        "业务场景",
        f"""<section class="page-title"><p class="eyebrow">Fixture workflow · zero API</p>
<h1>从一次报告到持续跟踪</h1>
<p class="notice">以下展示基于确定性 fixture 数据，用于演示工作流，非真实客户使用记录；不构成投资建议。</p></section>
<section><h2>分析师工作流</h2><div class="workflow-grid">
<article><span>01</span><h3>提出研究问题</h3><p>{html.escape(business['topic'])}</p></article>
<article><span>02</span><h3>取得带引用报告</h3><p>{business['evidence_count']} 条证据支撑 {business['report_claim_count']} 条报告论点。</p><a href="business-report.html">阅读 fixture 报告</a></article>
<article><span>03</span><h3>消费结构化结果</h3><p>对比表生成 {business['metric_count']} 行指标，并显式保留 period 与 scope。</p></article>
<article><span>04</span><h3>导出审计包</h3><p>{business['cited_evidence_count']} 条被引用证据闭合，缺失 {len(business['missing_evidence_ids'])} 条；导出报告、证据、manifest、账本与封面。</p></article>
<article><span>05</span><h3>隔期重跑</h3><p>演示快照从 {business['diff'].old_as_of.isoformat()} 跟踪至 {business['diff'].new_as_of.isoformat()}，变体明确标注为构造数据。</p></article>
<article><span>06</span><h3>阅读变化</h3><p>共检出 {len(business['diff'].changes)} 类/条变化，口径变化独立于数值变化。</p></article>
</div></section>
<section><h2>结构化对比表片段</h2><p>所有数字在构建时从 characterization fixture 读取，不在页面中另行录入。</p>
<div class="table-wrap"><table><thead><tr><th>实体</th><th>归一指标</th><th>期间</th><th>口径</th><th>数值</th><th>证据</th></tr></thead><tbody>{metric_rows}</tbody></table></div></section>
<section><h2>本期相较上期</h2>
<p class="notice">演示用构造数据：由同一 fixture 快照派生，不属于 Golden Set，不代表真实市场更新。</p>
<ul class="change-list">{changes}</ul>
<p class="paste-summary">{html.escape(business['diff'].paste_summary)}</p></section>
<section><h2>交付物</h2><div class="deliverables"><span>带引用 Markdown / JSON</span><span>结构化表格 / JSON / XLSX</span><span>引用闭合审计包</span><span>版本化 ResearchSnapshot</span><span>Markdown / JSON 变更报告</span></div></section>""",
    )


def _business_report_page(business: dict[str, Any]) -> str:
    return _layout(
        "业务场景报告",
        "<section class='page-title'><p class='eyebrow'>Deterministic fixture report</p>"
        "<h1>可追溯研究报告</h1>"
        "<p class='notice'>该报告来自 characterization fixture，用于工作流演示，"
        "非真实客户使用记录。</p></section>"
        f"<article class='report-body'>{_markdown_to_html(business['report'])}</article>",
    )


def _reports_index(reports: list[dict[str, Any]]) -> str:
    items = "".join(f'<article class="report-card"><h2><a href="{report["id"]}.html">{report["id"]}: {html.escape(report["topic"])}</a></h2><p>{html.escape(report["type"])} · {html.escape(report["difficulty"])}</p><p>Weighted score: {_fmt4(report["metrics"]["weighted_score"])}</p></article>' for report in reports)
    return _layout("报告 索引", f"<section class='page-title'><h1>精选 G3 报告</h1></section>{items}")


def _report_page(report: dict[str, Any], retrieval_as_of: str) -> str:
    metrics = report["metrics"]
    cards = [("Weighted", _fmt4(metrics["weighted_score"])), ("Citation support (3s)", _fmt4(metrics["citation_support_rate"])), ("Resolution", _fmt4(metrics["citation_resolution_rate"])), ("Repair retry", _fmt4(metrics["citation_repair_retry_rate"])), ("Uncited", _fmt4(metrics["uncited_claim_rate"]))]
    if report.get("false_premise"):
        cards.append(("False premise", "已识破"))
    return _layout(f"报告 {report['id']}", f"""<section class="page-title"><p class="eyebrow">{html.escape(report['type'])} · {html.escape(report['difficulty'])}</p><h1>{html.escape(report['id'])}</h1><p>检索语料截至 {retrieval_as_of}</p></section><section class="cards">{''.join(_card(label, value) for label, value in cards)}</section><article class="report-body">{_markdown_to_html(report['report_markdown'])}</article>""")


def _markdown_to_html(markdown: str) -> str:
    reference_map, references = _deduplicated_references(markdown)
    body_lines: list[str] = []
    in_list = False
    in_references = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("## 参考来源"):
            in_references = True
            continue
        if in_references or re.match(r"\[\^\d+\]:", line):
            continue
        if re.match(r"数据截至[:：]\s*\d{4}-\d{2}-\d{2}", line):
            continue
        if not line:
            if in_list:
                body_lines.append("</ul>")
                in_list = False
            continue
        line = _remap_citations(line, reference_map)
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
    body_lines.append("<h2>参考来源</h2><ol class='references'>" + "".join(references) + "</ol>")
    return "\n".join(body_lines)


def _deduplicated_references(markdown: str) -> tuple[dict[str, int], list[str]]:
    old_to_new: dict[str, int] = {}
    url_to_new: dict[str, int] = {}
    references: list[str] = []
    for line in markdown.splitlines():
        match = re.match(r"\[\^(\d+)\]:\s*(.*)", line.strip())
        if not match:
            continue
        old_id, description = match.groups()
        url_match = re.search(r"\b(?:https?|akshare)://[^\s)]+", description)
        if not url_match:
            raise ValueError(f"reference {old_id} has no URL")
        url = url_match.group(0)
        new_id = url_to_new.get(url)
        if new_id is None:
            new_id = len(url_to_new) + 1
            url_to_new[url] = new_id
            title = re.sub(r"\s*\(1970-01-01\)", "", description).strip()
            references.append(f'<li id="ref-{new_id}">{_inline(title)}</li>')
        old_to_new[old_id] = new_id
    if not references:
        raise ValueError("report has no references")
    return old_to_new, references


def _remap_citations(text: str, reference_map: dict[str, int]) -> str:
    def replace(match: re.Match[str]) -> str:
        old_id = match.group(1)
        if old_id not in reference_map:
            raise ValueError(f"citation {old_id} has no reference definition")
        return f"[^{reference_map[old_id]}]"
    return re.sub(r"\[\^(\d+)\]", replace, text)


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\[\^(\d+)\]", lambda match: f'<a class="citation" href="#ref-{match.group(1)}">[{match.group(1)}]</a>', escaped)
    return re.sub(r"((?:https?|akshare)://[^\s)]+)", lambda match: f'<a href="{match.group(1)}">{match.group(1)}</a>', escaped)


def _card(label: str, value: Any) -> str:
    return f"<div class='card'><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></div>"


def _fmt4(value: float) -> str:
    return f"{float(value):.4f}"


def _write_css(path: Path) -> None:
    path.write_text(""":root { color-scheme: light; --ink:#17202a; --muted:#5d6d7e; --line:#d7dee8; --bg:#f7f9fb; --accent:#14532d; --panel:#ffffff; } * { box-sizing:border-box; } body { margin:0; font-family:Inter,ui-sans-serif,system-ui,sans-serif; color:var(--ink); background:var(--bg); line-height:1.65; } a { color:#0f5f8f; } .site-header { display:flex; justify-content:space-between; gap:24px; padding:14px 28px; border-bottom:1px solid var(--line); background:#fff; } .brand { font-weight:800; color:var(--ink); text-decoration:none; } nav { display:flex; gap:16px; flex-wrap:wrap; } nav a { color:var(--muted); text-decoration:none; font-weight:650; } main { max-width:1120px; margin:0 auto; padding:36px 24px 80px; } .hero { padding:42px 0 26px; } .hero h1,.page-title h1 { max-width:920px; font-size:clamp(2rem,5vw,4.5rem); line-height:1.05; margin:0 0 18px; } .hero p,.page-title p { color:var(--muted); } .eyebrow { letter-spacing:.08em; font-weight:800; color:var(--accent); font-size:.78rem; } .notice { border-left:4px solid var(--accent); background:#eef7f0; padding:12px 16px; color:var(--ink)!important; } .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:22px 0 34px; } .card,.report-card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; } .card span { color:var(--muted); display:block; font-size:.88rem; } .card strong { display:block; font-size:1.4rem; margin-top:4px; } .flow { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:10px; } .flow span { border:1px solid var(--line); border-radius:999px; padding:10px 12px; text-align:center; background:var(--panel); font-weight:700; } .workflow-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; } .workflow-grid article { margin:0; padding:20px; border:1px solid var(--line); background:var(--panel); border-radius:8px; } .workflow-grid article>span { color:var(--accent); font-weight:900; } .workflow-grid h3 { margin:6px 0; } .table-wrap { overflow-x:auto; } .change-list { list-style:none; padding:0; display:grid; gap:10px; } .change-list li { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; } .change-list li>span { float:right; color:var(--accent); font-weight:800; } .change-list p { margin:6px 0 0; } .paste-summary { font-size:1.1rem; font-weight:650; background:#17202a; color:#fff; padding:20px; border-radius:8px; } .deliverables { display:flex; flex-wrap:wrap; gap:10px; } .deliverables span { border:1px solid var(--line); background:var(--panel); border-radius:999px; padding:8px 12px; } section,article { margin:0 0 38px; } table { border-collapse:collapse; width:100%; background:var(--panel); } th,td { border:1px solid var(--line); padding:10px 12px; text-align:left; vertical-align:top; } th { background:#edf3f8; } .button { display:inline-block; padding:10px 14px; background:var(--accent); color:#fff; border-radius:6px; text-decoration:none; font-weight:750; } .report-body { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:20px; overflow-wrap:anywhere; } .citation { font-weight:800; text-decoration:none; } .references { padding-left:20px; } code { background:#edf3f8; padding:2px 5px; border-radius:4px; } @media (max-width:720px) { .site-header { align-items:flex-start; flex-direction:column; } main { padding:24px 16px 60px; } }\n""", encoding="utf-8")


if __name__ == "__main__":
    main()
