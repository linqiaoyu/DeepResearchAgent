"""Build the static showcase exclusively from Golden v1.1 release assets."""

from __future__ import annotations

import html
import json
import re
import shutil
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from deepresearch_agent.provenance import (  # noqa: E402
    FLAG_CLASSIFICATIONS,
    RunManifest,
    settings_flag_snapshot,
)
from deepresearch_agent.research_snapshot import (  # noqa: E402
    build_demo_followup,
    build_research_snapshot,
    diff_research_snapshots,
)
from deepresearch_agent.schemas import Evidence, ResearchState  # noqa: E402
from deepresearch_agent.settings import Settings  # noqa: E402
from deepresearch_agent.structured_output import build_structured_output  # noqa: E402

DIST = ROOT / "site" / "dist"
FINAL_NIO_PACKAGE = ROOT / "artifacts" / "087" / "live-nio-zh"
AB_RESULTS_PATH = ROOT / "_collab" / "087" / "ab" / "results.json"
SHOWCASE_PATH = ROOT / "data" / "demo" / "g3_showcase.json"
G3_PATH = ROOT / "data" / "golden_set" / "v1" / "results" / "g3_judge_v11.json"
CITATION_PATH = ROOT / "data" / "golden_set" / "v1" / "results" / "g3_citation_support_3s.json"
AUDIT_PATH = ROOT / "data" / "golden_set" / "v1" / "audit_v11.json"
FREEZE_PATH = ROOT / "data" / "golden_set" / "v1" / "freeze.md"
BUSINESS_FIXTURE_PATH = ROOT / "tests" / "golden_output" / "wealth_research.json"
RAG_RELEASE_EVIDENCE_PATH = ROOT / "data" / "round" / "047_release_evidence.json"
FORBIDDEN_V10_NUMBERS = ("0.7803", "0.7999")
HISTORICAL_JUDGE_DECOMPOSITION = "0.6134 + 0.1865 - 0.0585 = 0.7414"
RELEASE_LEAK_PATTERNS = {
    "credential": re.compile(
        r"(?i)(?:api[_-]?key|authorization)\s*[:=]\s*(?:bearer\s+)?[a-z0-9._-]{8,}"
    ),
    "qdrant_endpoint": re.compile(r"(?i)https?://[^\s\"']*(?:qdrant|cloud\.qdrant)[^\s\"']*"),
    "absolute_path": re.compile(r"(?:^|[\s\"'])/(?:Users|home|private|var/folders|tmp)/"),
    "raw_corpus_reference": re.compile(r"(?i)(?:data/(?:corpus|recordings)/|<raw-corpus>)"),
}
RELEASE_TEXT_SUFFIXES = {".css", ".html", ".json", ".md", ".txt"}


def main() -> None:
    facts = _final_showcase_facts(FINAL_NIO_PACKAGE)
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "assets").mkdir(parents=True)
    _write_final_css(DIST / "assets" / "styles.css")
    (DIST / "index.html").write_text(
        _final_home_page(facts), encoding="utf-8"
    )
    _assert_site(DIST)
    _assert_showcase_contract(
        (DIST / "index.html").read_text(encoding="utf-8"),
        (DIST / "assets" / "styles.css").read_text(encoding="utf-8"),
    )
    manifest = {
        "generated_from": "artifacts/087/live-nio-zh",
        "facts": facts,
        "files": sorted(str(path.relative_to(DIST)) for path in DIST.rglob("*") if path.is_file()),
    }
    (DIST / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    build_log = _release_build_log(len(manifest["files"]) + 1)
    _assert_release_safety(DIST, build_log)
    print(build_log, end="")


def _final_showcase_facts(package: Path) -> dict[str, Any]:
    report = (package / "report.md").read_text(encoding="utf-8")
    evidence = _read_json(package / "audit_bundle" / "evidence.json")
    manifest = _read_json(package / "audit_bundle" / "manifest.json")
    reader_audit = _read_json(package / "audit_bundle" / "reader_audit.json")
    if not isinstance(evidence, list) or len(evidence) < 2:
        raise SystemExit("final showcase needs at least two final-package evidence records")
    values = re.findall(r"(?<![\w,])\d[\d,]*(?:\.\d+)?%?", report)
    gross = next((item for item in evidence if item.get("structured_record", {}).get("metric_name") == "毛利"), None)
    revenue = next((item for item in evidence if item.get("structured_record", {}).get("metric_name") == "营业收入"), None)
    if not isinstance(gross, dict) or not isinstance(revenue, dict):
        raise SystemExit("final showcase needs gross-profit and revenue evidence")
    started = datetime.fromisoformat(manifest["started_at"].replace("Z", "+00:00"))
    ended = datetime.fromisoformat(manifest["ended_at"].replace("Z", "+00:00"))
    rag_cost = sum(
        float(json.loads(line).get("cost_cny", 0))
        for line in (package / "runtime" / "rag_ledger.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    with sqlite3.connect(package / "runtime" / "research.db") as conn:
        evidence_total = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        source_row = conn.execute(
            """
            SELECT id, extract_text FROM evidence
            WHERE source_url LIKE ? AND extract_text LIKE ?
            LIMIT 1
            """,
            ("%nio-20241231x20f.htm%", "%Total revenues%"),
        ).fetchone()
    source_origin = "run"
    if source_row is None:
        source_origin = "registered_corpus"
        with sqlite3.connect(ROOT / "data" / "runtime" / "085-assets.db") as conn:
            source_row = conn.execute(
                """
                SELECT c.id, c.content
                FROM chunk AS c
                JOIN document_version AS dv ON c.document_version_id = dv.id
                JOIN document AS d ON dv.document_id = d.id
                WHERE d.canonical_url LIKE ? AND c.content LIKE ?
                LIMIT 1
                """,
                ("%nio-20241231x20f.htm", "%65,731,559%"),
            ).fetchone()
    if source_row is None:
        raise SystemExit("final showcase needs the NIO 20-F revenue excerpt")
    source_id, source_excerpt = source_row
    source_excerpt = html.unescape(str(source_excerpt)).replace("\u200b", " ")
    source_excerpt = re.sub(r"\s+", " ", source_excerpt)
    source_amount = next(
        value
        for value in re.findall(r"\d[\d,]*(?:\.\d+)?", source_excerpt)
        if value == "65,731,559"
    )
    source_position = source_excerpt.index(source_amount)
    excerpt_start = max(0, source_position - 360)
    excerpt_end = min(len(source_excerpt), source_position + 440)
    if excerpt_start:
        excerpt_start = source_excerpt.find(" ", excerpt_start) + 1
    if excerpt_end < len(source_excerpt):
        excerpt_end = source_excerpt.rfind(" ", 0, excerpt_end)
    source_excerpt = source_excerpt[excerpt_start:excerpt_end]
    cited_sources = len(re.findall(r"^\[\^\d+\]:", report, re.MULTILINE))
    capabilities = _capability_matrix()
    display_numbers = values + [
        f"{float(manifest['cost_cny_total']):.8f}",
        f"{rag_cost:.7f}",
        str(round((ended - started).total_seconds(), 3)),
        str(evidence_total),
        str(cited_sources),
        source_amount,
        *re.findall(r"\d[\d,]*(?:\.\d+)?%?", source_excerpt),
        *(value for item in capabilities for value in item["numbers"]),
    ]
    return {
        "package": str(package.relative_to(ROOT)),
        "report_opening": report.splitlines()[:3],
        "report": report,
        "gross": str(gross["structured_record"]["value"]),
        "revenue": str(revenue["structured_record"]["value"]),
        "margin": next(value for value in values if value.endswith("%")),
        "gross_evidence_id": str(gross["evidence_id"]),
        "revenue_evidence_id": str(revenue["evidence_id"]),
        "source_excerpt": str(source_excerpt),
        "source_evidence_id": str(source_id),
        "source_origin": source_origin,
        "source_amount": source_amount,
        "workflow_cost": f"{float(manifest['cost_cny_total']):.8f}",
        "rag_cost": f"{rag_cost:.7f}",
        "elapsed_seconds": str(round((ended - started).total_seconds(), 3)),
        "evidence_total": str(evidence_total),
        "cited_sources": str(cited_sources),
        "provider_fidelity": {
            key: str(manifest["actual_provider_fidelity"][key])
            for key in ("llm", "search", "rag_search", "structured_data")
        },
        "audit_closure": str(reader_audit["audit_citation_closure"]),
        "capabilities": capabilities,
        "display_numbers": display_numbers,
    }


def _capability_matrix() -> list[dict[str, Any]]:
    try:
        from scripts.check_087_report_shape import measure
    except ModuleNotFoundError:
        from check_087_report_shape import measure

    payload = _read_json(AB_RESULTS_PATH)
    pairs = {item["capability"]: item for item in payload["pairs"]}
    flags = settings_flag_snapshot(
        Settings(storage_path=Path("research.db")),
        include_disabled_experimental=True,
    )
    capabilities: list[dict[str, Any]] = []
    for flag in sorted(FLAG_CLASSIFICATIONS):
        capability = flag.removesuffix("_ENABLED")
        pair = pairs.get(capability)
        if pair is None:
            capabilities.append(
                {
                    "flag": flag,
                    "default": bool(flags[flag]),
                    "decision": "not_measured",
                    "numbers": [],
                }
            )
            continue
        paths = [
            (AB_RESULTS_PATH.parent / pair[name]).resolve()
            for name in ("off_package", "on_package")
        ]
        visible = [
            measure((path / "report.md").read_text(encoding="utf-8"))["reader_visible_lines"]
            for path in paths
        ]
        capabilities.append(
            {
                "flag": flag,
                "default": bool(flags[flag]),
                "decision": pair["decision"],
                "numbers": [str(value) for value in visible],
            }
        )
    if len(capabilities) != len(FLAG_CLASSIFICATIONS):
        raise SystemExit("final showcase capability matrix is incomplete")
    return capabilities


def _fact(value: str, *, evidence_id: str | None = None) -> str:
    identity = f' data-evidence-id="{html.escape(evidence_id)}"' if evidence_id else ""
    return f'<span class="fact" data-fact="{html.escape(value)}"{identity}>{html.escape(value)}</span>'


def _final_home_page(facts: dict[str, Any]) -> str:
    opening = "<br>".join(html.escape(line) for line in facts["report_opening"])
    gross = _fact(facts["gross"], evidence_id=facts["gross_evidence_id"])
    revenue = _fact(facts["revenue"], evidence_id=facts["revenue_evidence_id"])
    margin = _fact(facts["margin"], evidence_id=facts["gross_evidence_id"])
    source_amount = _fact(
        facts["source_amount"], evidence_id=facts["revenue_evidence_id"]
    )
    source_excerpt = html.escape(facts["source_excerpt"]).replace(
        html.escape(facts["source_amount"]),
        f"<mark>{source_amount}</mark>",
    )
    cards = "".join(_capability_card(item) for item in facts["capabilities"])
    fidelity = facts["provider_fidelity"]
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DeepResearchAgent · 可审计投研</title><link rel="stylesheet" href="assets/styles.css"></head><body data-showcase="087"><main>
<section data-screen="one" class="screen hero"><p class="eyebrow">FINANCIAL RESEARCH, WITH RECEIPTS</p><h1>让结论<br>回到原文。</h1><p class="opening">{opening}</p></section>
<section data-screen="two" class="screen proof"><p class="eyebrow">NUMBER → SOURCE</p><h2>数字不是终点。它有来处。</h2><div class="mapping"><p>营业收入 {revenue}</p><i aria-hidden="true"></i><blockquote data-source-evidence-id="{html.escape(facts['source_evidence_id'])}">{source_excerpt}</blockquote></div><p class="formula">毛利率（推导值）：{gross} / {revenue} = {margin}</p></section>
<section data-screen="three" class="screen"><p class="eyebrow">MEASURED CAPABILITIES</p><h2>能力，先用真实运行说话。</h2><div class="capability-matrix">{cards}</div></section>
<section data-screen="four" class="screen bill"><p class="eyebrow">ONE REAL RUN</p><h2>一次报告的账单。</h2><dl><div><dt>workflow CNY</dt><dd>{_fact(facts['workflow_cost'])}</dd></div><div><dt>RAG CNY</dt><dd>{_fact(facts['rag_cost'])}</dd></div><div><dt>elapsed seconds</dt><dd>{_fact(facts['elapsed_seconds'])}</dd></div><div><dt>evidence → cited sources</dt><dd>{_fact(facts['evidence_total'])} → {_fact(facts['cited_sources'])}</dd></div></dl><ul class="fidelity"><li>LLM: {html.escape(fidelity['llm'])}</li><li>Search + RAG: {html.escape(fidelity['search'])} / {html.escape(fidelity['rag_search'])}</li><li>Structured data: {html.escape(fidelity['structured_data'])}</li></ul><p>citation closure={html.escape(facts['audit_closure'])}</p></section>
<section data-screen="five" class="screen"><p class="eyebrow">REPRODUCE</p><h2>从本地 fixture 开始。</h2><pre>python3 -m venv .venv\n.venv/bin/python -m pip install -e ".[dev]"\n.venv/bin/python scripts/gate.py</pre></section>
</main><noscript>五个页面区块均以静态 HTML 输出；禁用 JavaScript 仍可完整阅读。</noscript></body></html>'''


def _capability_card(item: dict[str, Any]) -> str:
    state = "亮态" if item["decision"] == "promoted" else "暗态"
    if item["decision"] == "not_measured":
        detail = "未纳入单次 A/B；保持默认"
    else:
        left, right = (_fact(value) for value in item["numbers"])
        outcome = "实测增益" if item["decision"] == "promoted" else "已实现，实测无增益"
        detail = f"{outcome}：读者行 {left} → {right}"
    default = "默认开启" if item["default"] else "默认关闭"
    return (
        f'<article class="capability {state}" data-capability="{html.escape(item["flag"])}">'
        f"<b>{html.escape(item['flag'])}</b><span>{default}</span><p>{detail}</p></article>"
    )


def _write_final_css(path: Path) -> None:
    path.write_text('''*{box-sizing:border-box}body{margin:0;background:#f7f7f5;color:#161616;font:18px/1.6 ui-sans-serif,system-ui}.screen{min-height:100vh;max-width:1100px;margin:auto;padding:12vh 7vw;border-bottom:1px solid #ddd}.hero{display:grid;align-content:center}.hero h1{font-size:clamp(64px,12vw,160px);line-height:.9;letter-spacing:-.08em;margin:0}.eyebrow{font-size:.72rem;letter-spacing:.18em;font-weight:800;color:#52706a}.opening{font-family:ui-monospace,monospace;margin-top:3rem}.proof h2{font-size:clamp(42px,7vw,92px);line-height:1;margin:0 0 4rem}.mapping{display:grid;grid-template-columns:1fr 90px 1fr;align-items:center;gap:20px}.mapping i{height:2px;background:#52706a;animation:draw 2s ease-in-out infinite alternate}.mapping blockquote{margin:0;padding:24px;border:1px solid #bbb;font-family:ui-monospace,monospace}.mapping mark{background:#e9e66b;padding:0 3px}.formula{font-size:clamp(24px,4vw,52px);margin-top:4rem}.fact{font-variant-numeric:tabular-nums;font-weight:800}.capability-matrix{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}.capability{padding:16px;border:1px solid #bbb;background:#fff}.capability b,.capability span{display:block}.capability b{font-size:.72rem;overflow-wrap:anywhere}.capability span{font-size:.7rem;color:#666}.capability p{font-size:.76rem;margin:.7rem 0 0}.capability.亮态{border-color:#52706a;background:#e6f0ec}.capability.暗态{opacity:.75}.fidelity{padding:0;list-style:none;display:grid;gap:8px}.fidelity li{padding:10px;background:#fff;border-left:3px solid #52706a}dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}dl div,pre{padding:24px;background:#fff;border:1px solid #ddd}dt{font-size:.75rem;color:#666;text-transform:uppercase}dd{margin:.5rem 0 0;font-size:clamp(24px,4vw,50px)}pre{white-space:pre-wrap;overflow:auto}@keyframes draw{from{transform:scaleX(.2);transform-origin:left}to{transform:scaleX(1)}}@media(max-width:650px){.mapping,dl{grid-template-columns:1fr}.mapping i{width:2px;height:48px;justify-self:center;animation:none}}''', encoding="utf-8")


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


def _validate_rag_release_evidence(evidence: dict[str, Any]) -> None:
    required = ("corpus", "index", "retrieval", "trace", "limitations")
    if evidence.get("schema_version") != "047-release-evidence-v1" or any(key not in evidence for key in required):
        raise SystemExit("RAG release evidence has an invalid schema")
    if evidence["corpus"].get("documents") != 60 or evidence["corpus"].get("chunks") != 22953:
        raise SystemExit("RAG release evidence corpus summary is not the reviewed 047 result")
    if evidence["retrieval"].get("quality_gate") != "FAIL":
        raise SystemExit("RAG release evidence must retain the 047 quality-gate result")


def _assert_site(
    dist: Path,
    business: dict[str, Any] | None = None,
) -> None:
    index = dist / "index.html"
    if index.is_file() and 'data-showcase="087"' in index.read_text(encoding="utf-8"):
        text = index.read_text(encoding="utf-8")
        screens = re.findall(r'<section data-screen="([^"]+)"', text)
        mappings = re.findall(
            r'data-fact="[^"]+" data-evidence-id="([^"]+)"', text
        )
        capabilities = re.findall(r'data-capability="([^"]+)"', text)
        source_mappings = re.findall(
            r'data-source-evidence-id="([^"]+)"', text
        )
        if len(screens) != 5 or len(set(screens)) != 5:
            raise SystemExit("final showcase must expose five readable screens")
        if not mappings:
            raise SystemExit("final showcase needs a number-to-evidence mapping")
        if len(capabilities) != 25 or len(set(capabilities)) != 25:
            raise SystemExit("final showcase must expose the full capability matrix")
        if len(source_mappings) != 1:
            raise SystemExit("final showcase needs one highlighted source mapping")
        return
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


def _assert_showcase_contract(home: str, stylesheet: str) -> None:
    if 'data-showcase="087"' in home:
        required_home = (
            "NUMBER → SOURCE",
            "MEASURED CAPABILITIES",
            "ONE REAL RUN",
            "REPRODUCE",
            "毛利率（推导值）",
            "capability-matrix",
            "Structured data:",
        )
        if any(token not in home for token in required_home):
            raise SystemExit("final showcase is missing a required screen")
        if (
            "@keyframes draw" not in stylesheet
            or ".mapping" not in stylesheet
            or ".capability-matrix" not in stylesheet
        ):
            raise SystemExit("final showcase is missing its progressive motion mapping")
        return
    required_home = (
        "RESEARCH, WITH RECEIPTS",
        "无实时 LLM、搜索或付费调用",
        "浏览精选报告",
        "MEASURABLE, NOT MERELY CLAIMED",
        "RELEASE DISCIPLINE",
    )
    missing_home = [token for token in required_home if token not in home]
    if missing_home:
        raise SystemExit(f"showcase home misses required presentation contract: {missing_home}")
    required_styles = (".hero-home", ".proof-panel", ".metric-section", ".release-section")
    missing_styles = [selector for selector in required_styles if selector not in stylesheet]
    if missing_styles:
        raise SystemExit(f"showcase stylesheet misses visual system selectors: {missing_styles}")


def _release_build_log(file_count: int) -> str:
    """Return publishable build output without a workstation-specific path."""

    return f"built site/dist\nfiles {file_count}\nvalidation ok\n"


def _assert_release_safety(dist: Path, build_log: str) -> None:
    """Reject secrets, service endpoints, local paths, and raw corpus links."""

    texts = {"build.log": build_log}
    for path in dist.rglob("*"):
        if path.is_file() and path.suffix in RELEASE_TEXT_SUFFIXES:
            texts[str(path.relative_to(dist))] = path.read_text(encoding="utf-8")
    leaks = [
        f"{name}:{relative_path}"
        for relative_path, text in texts.items()
        for name, pattern in RELEASE_LEAK_PATTERNS.items()
        if pattern.search(text)
    ]
    if leaks:
        raise SystemExit(f"release leak scan failed: {', '.join(leaks)}")


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
<meta name="theme-color" content="#0b172a"><meta name="description" content="DeepResearchAgent 的可复核研究成果、评测证据与复现路径。">
<meta property="og:image" content="https://deepresearch-agent.jacksonyu1109.workers.dev/assets/og.png"><meta property="og:image:alt" content="DeepResearchAgent：让每一个研究结论，都经得起回看。">
<title>{html.escape(title)} · DeepResearchAgent</title><link rel="stylesheet" href="{prefix}assets/styles.css"></head>
<body><a class="skip-link" href="#content">跳至内容</a><header class="site-header"><a class="brand" href="{prefix}index.html"><span class="brand-mark">DR</span><span>DeepResearch<br><em>Agent</em></span></a><nav aria-label="主导航">
<a href="{prefix}reports/index.html">成果报告</a><a href="{prefix}scenarios.html">工作流演示</a><a href="{prefix}methodology.html">评测方法</a><a href="{prefix}rag.html">RAG 证据</a><a href="{prefix}reproduce.html">复现路径</a>
<a class="nav-github" href="https://github.com/linqiaoyu/DeepResearchAgent">GitHub ↗</a></nav></header><main id="content">{content}</main><footer><span>DeepResearchAgent</span><span>静态展示 · 冻结语料 · 可审计产物</span></footer></body></html>"""


def _home_page(showcase: dict[str, Any], validation: dict[str, Any]) -> str:
    summary = showcase["summary"]
    cards = [
        ("G3 综合评分", _fmt4(summary["avg_weighted_score"]), "冻结语料上的多维中位数"),
        ("事实准确性", _fmt4(summary["avg_fact_accuracy"]), "按锁定量规评分"),
        ("引用支持率", _fmt4(summary["avg_citation_support_rate"]), "逐 claim、三次采样多数决"),
        ("引用可解析率", _fmt4(summary["avg_citation_resolution_rate"]), "脚注可追溯至原始来源"),
    ]
    return _layout(
        "首页",
        f"""<section class="hero hero-home"><div class="hero-copy"><p class="eyebrow">RESEARCH, WITH RECEIPTS</p><h1>让每一个研究结论，都经得起回看。</h1>
<p class="hero-lede">DeepResearchAgent 将研究、引文、数值审计与评测发布连接成一条可复核的交付链路。这里展示的是冻结资产构建的静态成果，而非模拟的在线服务。</p>
<div class="hero-actions"><a class="button button-primary" href="reports/index.html">浏览精选报告 <span>→</span></a><a class="button button-quiet" href="methodology.html">查看评测证据</a></div>
<p class="boundary-note"><span></span> 检索语料截至 {validation['retrieval_as_of']} · 无实时 LLM、搜索或付费调用</p></div>
<aside class="proof-panel" aria-label="发布核验摘要"><div class="proof-top"><span>RELEASE CHECK</span><b>VERIFIED</b></div><div class="score-orbit"><strong>{_fmt4(summary['avg_weighted_score'])}</strong><span>G3 composite</span></div><div class="proof-lines"><p><i></i><span>证据引用已解析</span><b>{_fmt4(summary['avg_citation_resolution_rate'])}</b></p><p><i></i><span>错误前提已识别</span><b>{summary['false_premise']['passed']}/2</b></p><p><i></i><span>数值审计缺陷</span><b>{validation['audit_counts']['DEFECT']}</b></p></div><div class="proof-caption">Golden v1.1 · 发布态</div></aside></section>
<section class="metric-section"><div class="section-kicker"><p class="eyebrow">MEASURABLE, NOT MERELY CLAIMED</p><h2>把可靠性变成可检查的交付物。</h2></div><div class="cards metric-cards">{''.join(_card(label, value, detail) for label, value, detail in cards)}</div></section>
<section class="story-grid"><div class="story-intro"><p class="eyebrow">FROM QUESTION TO EVIDENCE</p><h2>不是一段“看起来像答案”的文字。</h2><p>每份展示报告将研究结论与来源脚注并列呈现；发布前经过引用支持抽样、数值与口径检查，以及冻结评测回归。</p><a class="text-link" href="scenarios.html">查看端到端工作流 <span>→</span></a></div><div class="chain"><article><span>01</span><h3>计划与取证</h3><p>拆解问题，按来源和期间组织可追溯证据。</p></article><article><span>02</span><h3>审校与回流</h3><p>将数字、口径、引用与不确定性置于同一审计链。</p></article><article><span>03</span><h3>发布与复现</h3><p>以固定版本资产生成报告、指标与发布清单。</p></article></div></section>
<section class="release-section"><div><p class="eyebrow">RELEASE DISCIPLINE</p><h2>展示的每个数字，都有自己的位置。</h2></div><div class="release-grid"><article><b>{validation['audit_counts']['PASS']}</b><h3>审计通过</h3><p>实体、指标、期间、口径和数值摘录的联合核验。</p></article><article><b>{validation['citation_samples']}×</b><h3>引用支持采样</h3><p>逐 claim 多次判断，避免单次模型判断被当作结论。</p></article><article><b>0</b><h3>实时依赖</h3><p>公开页只读取受版本控制的发布资产，成本与密钥均不暴露。</p></article></div></section>
<section class="report-cta"><div><p class="eyebrow">CURATED OUTPUTS</p><h2>阅读可回溯的研究成果。</h2><p>精选报告保留指标、引用与来源列表；业务场景展示结构化交付和隔期差分。</p></div><div class="cta-links"><a class="button button-primary" href="reports/index.html">G3 报告库 <span>→</span></a><a class="button button-quiet" href="business-report.html">Fixture 报告示例</a></div></section>""",
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
    return _layout("复现", """<section class="page-title"><h1>复现与可部署资产</h1><p>静态站不依赖后端；仓库保留 API/UI 演示资产。</p></section><section><h2>三步</h2><ol><li>复制仓库并配置服务器侧 .env。</li><li>运行 <code>docker compose up -d --build</code>。</li><li>访问 <code>/demo</code> 或 Streamlit UI。</li></ol></section><section><h2>RAG MVP 边界</h2><ul><li>摄取仅接受本地、manifest 列出的公开 PDF、HTML 或 TXT，并保留文件 hash、版本与字符范围。</li><li>默认没有已配置的向量索引，因此 <code>rag_search</code> 返回明确的空结果，不伪造来源或指标。</li><li>rerank 默认开启的单项检索收益尚未经测量；未来展示的整条流水线提升也不可归因到 rerank。</li><li>公开站点只包含冻结发布资产，不包含 API key、私有 endpoint、运行机路径或全文语料。</li></ul></section>""")


def _rag_page(evidence: dict[str, Any]) -> str:
    corpus, index, retrieval, trace = (evidence[key] for key in ("corpus", "index", "retrieval", "trace"))
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in evidence["limitations"])
    return _layout(
        "RAG 证据",
        f"""<section class="page-title"><p class="eyebrow">ROUND 047 · REVIEWED RELEASE EVIDENCE</p><h1>RAG 是一组可复核的结果。</h1><p>此页只读取版本控制的脱敏摘要；不包含 endpoint、密钥、运行机路径或原始全文。</p></section>
<section><h2>检索链路</h2><div class="workflow-grid"><article><span>01</span><h3>SQLite 词法检索</h3><p>候选 Top-50</p></article><article><span>02</span><h3>Qdrant 稠密检索</h3><p>以 index_version 与 as-of 过滤，候选 Top-50。</p></article><article><span>03</span><h3>RRF 融合</h3><p>只传递 chunk identity；正文仍由权威存储读取。</p></article><article><span>04</span><h3>DashScope rerank</h3><p>交付 Top-{trace['delivered_candidates']}，降级状态显式记录。</p></article></div></section>
<section><h2>语料、索引与真实 trace</h2><table><tbody><tr><th>语料</th><td>{html.escape(corpus['version'])} · {corpus['documents']} 份公开原件 · {corpus['chunks']} active chunks</td></tr><tr><th>语料指纹</th><td><code>{html.escape(corpus['fingerprint'])}</code></td></tr><tr><th>索引</th><td><code>{html.escape(index['version'])}</code> · 重建 {index['rebuild_seconds']} s · ¥{index['cost_cny']:.6f}</td></tr><tr><th>真实检索 trace</th><td>{html.escape(trace['kind'])}：词法 {trace['lexical_candidates']} / 稠密 {trace['dense_candidates']} / 交付 {trace['delivered_candidates']}；rerank={trace['rerank_status']}；¥{trace['cost_cny']:.7f}</td></tr></tbody></table></section>
<section><h2>冻结 test split：BM25 基线 vs hybrid + rerank</h2><table><thead><tr><th>链路</th><th>Recall@20</th><th>nDCG@10</th></tr></thead><tbody><tr><td>BM25</td><td>{retrieval['bm25']['recall_at_20']:.4f}</td><td>{retrieval['bm25']['ndcg_at_10']:.4f}</td></tr><tr><td>Hybrid + rerank</td><td>{retrieval['hybrid_rerank']['recall_at_20']:.4f}</td><td>{retrieval['hybrid_rerank']['ndcg_at_10']:.4f}</td></tr></tbody></table><p class="notice">质量门槛：<strong>{html.escape(retrieval['quality_gate'])}</strong>。{html.escape(retrieval['decision'])}</p></section>
<section><h2>MVP 限制清单</h2><ul>{limitations}</ul></section>""",
    )


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
    # Characterization snapshots intentionally normalize wall-clock timestamps.
    # Restore a fixed value in memory only, so the immutable fixture remains
    # byte-stable while the typed manifest can be reconstructed for the demo.
    manifest_payload["decision_summary"] = [
        {**decision, "timestamp": fixed_time}
        for decision in manifest_payload.get("decision_summary", [])
    ]
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
    items = "".join(
        f'<article class="report-card"><div class="report-meta"><span>{html.escape(report["id"])}</span><span>{html.escape(report["difficulty"])}</span></div><h2><a href="{report["id"]}.html">{html.escape(report["topic"])}</a></h2><p>{html.escape(report["type"])}</p><div class="report-score"><span>G3 综合评分</span><strong>{_fmt4(report["metrics"]["weighted_score"])}</strong></div><a class="text-link" href="{report["id"]}.html">阅读报告 <span>→</span></a></article>'
        for report in reports
    )
    return _layout("报告 索引", f"<section class='page-title page-title-rich'><p class='eyebrow'>CURATED, EVALUATED, TRACEABLE</p><h1>精选研究报告</h1><p>来自 Golden v1.1 发布资产。每份报告均显示评测分数，并保留脚注到来源的可解析映射。</p></section><section class='report-grid'>{items}</section>")


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


def _card(label: str, value: Any, detail: str = "") -> str:
    detail_html = f"<p>{html.escape(detail)}</p>" if detail else ""
    return f"<div class='card'><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong>{detail_html}</div>"


def _fmt4(value: float) -> str:
    return f"{float(value):.4f}"


def _write_css(path: Path) -> None:
    path.write_text(
        """
:root{--navy:#0b172a;--ink:#10203a;--muted:#60708a;--mist:#eef3f8;--line:#d9e2ed;--paper:#fbfcfe;--panel:#fff;--teal:#008d8b;--teal-soft:#dff4f1;--gold:#f1b84b;--shadow:0 18px 50px rgba(17,37,66,.09)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,"Noto Sans SC","PingFang SC",ui-sans-serif,system-ui,sans-serif;line-height:1.65}a{color:inherit}.skip-link{position:absolute;left:12px;top:-50px;background:#fff;color:var(--navy);padding:8px 12px;z-index:4}.skip-link:focus{top:12px}.site-header,footer{max-width:1280px;margin:auto;padding:20px 38px}.site-header{display:flex;align-items:center;justify-content:space-between;gap:30px;border-bottom:1px solid var(--line)}.brand{display:flex;gap:10px;align-items:center;color:var(--navy);font-size:.82rem;font-weight:800;letter-spacing:.04em;line-height:1.05;text-decoration:none}.brand em{color:var(--teal);font-style:normal}.brand-mark{display:grid;place-items:center;width:34px;height:34px;background:var(--navy);color:#fff;font-size:.65rem;letter-spacing:0;border-radius:9px}nav{display:flex;gap:23px;align-items:center;flex-wrap:wrap}nav a{color:var(--muted);font-size:.87rem;font-weight:700;text-decoration:none}nav a:hover,.text-link:hover{color:var(--teal)}.nav-github{border:1px solid var(--line);padding:7px 11px;border-radius:999px;color:var(--navy)!important}main{max-width:1200px;margin:auto;padding:0 38px 94px}footer{border-top:1px solid var(--line);color:var(--muted);font-size:.78rem;display:flex;justify-content:space-between;gap:16px}.hero-home{display:grid;grid-template-columns:minmax(0,1.18fr) minmax(310px,.72fr);gap:70px;align-items:center;padding:90px 0 78px}.eyebrow{margin:0 0 13px;color:var(--teal);font-size:.71rem;font-weight:850;letter-spacing:.15em}.hero h1,.page-title h1{margin:0;color:var(--navy);letter-spacing:-.055em;line-height:1.02}.hero h1{max-width:700px;font-size:clamp(3rem,6.5vw,5.65rem)}.hero-lede{max-width:630px;margin:27px 0 0;color:var(--muted);font-size:1.08rem}.hero-actions,.cta-links{display:flex;gap:12px;flex-wrap:wrap;margin-top:31px}.button{display:inline-flex;align-items:center;gap:11px;padding:12px 17px;border:1px solid transparent;border-radius:10px;font-size:.9rem;font-weight:800;text-decoration:none;transition:.2s ease}.button:hover,.report-card:hover{transform:translateY(-3px);box-shadow:var(--shadow)}.button-primary{background:var(--navy);color:#fff}.button-quiet{border-color:var(--line);background:#fff;color:var(--navy)}.boundary-note{display:flex;align-items:center;gap:8px;margin:25px 0 0;color:var(--muted);font-size:.77rem}.boundary-note span,.proof-lines i{display:block;width:7px;height:7px;border-radius:50%;background:var(--teal)}.proof-panel{position:relative;overflow:hidden;background:var(--navy);color:#fff;border-radius:22px;padding:24px;box-shadow:var(--shadow)}.proof-panel:before{position:absolute;content:"";width:250px;height:250px;right:-100px;top:-112px;border:1px solid #496583;border-radius:50%;box-shadow:0 0 0 30px rgba(255,255,255,.03)}.proof-top,.proof-lines p{position:relative;display:flex;justify-content:space-between;align-items:center;gap:10px}.proof-top{font-size:.67rem;font-weight:800;letter-spacing:.12em;color:#aebed3}.proof-top b,.release-grid b{color:var(--gold)}.score-orbit{position:relative;margin:34px 0 26px;width:160px;height:160px;display:flex;flex-direction:column;justify-content:center;text-align:center;border:12px solid var(--teal);border-top-color:#496583;border-right-color:#496583;border-radius:50%}.score-orbit strong{font-size:1.9rem;letter-spacing:-.06em}.score-orbit span{font-size:.72rem;color:#aebed3}.proof-lines{border-top:1px solid rgba(255,255,255,.14)}.proof-lines p{margin:0;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.14);font-size:.77rem}.proof-lines span{margin-right:auto;color:#d4deeb}.proof-caption{position:relative;margin-top:17px;color:#9eafc5;font-size:.68rem;letter-spacing:.08em}.metric-section{padding:70px 0 77px;border-top:1px solid var(--line)}.section-kicker{margin-bottom:28px}.section-kicker h2,.story-grid h2,.release-section h2,.report-cta h2{max-width:650px;margin:0;line-height:1.12;letter-spacing:-.04em;font-size:clamp(1.9rem,4vw,3.15rem);color:var(--navy)}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:13px}.card{min-height:180px;padding:21px;background:var(--panel);border:1px solid var(--line);border-radius:15px;box-shadow:0 5px 20px rgba(17,37,66,.035)}.card span,.card p{color:var(--muted);font-size:.78rem;font-weight:750}.card strong{display:block;margin:20px 0 3px;color:var(--navy);font-size:2rem;letter-spacing:-.06em}.card p{margin:0;font-size:.74rem;line-height:1.5;font-weight:400}.story-grid{display:grid;grid-template-columns:.79fr 1.21fr;gap:75px;padding:74px 0}.story-intro>p:not(.eyebrow),.report-cta p:not(.eyebrow){max-width:540px;color:var(--muted)}.text-link{display:inline-flex;gap:8px;align-items:center;margin-top:12px;color:var(--navy);font-size:.88rem;font-weight:850;text-decoration:none}.chain{display:grid;gap:12px}.chain article{display:grid;grid-template-columns:45px 1fr;column-gap:15px;margin:0;padding:20px 0;border-top:1px solid var(--line)}.chain article:last-child{border-bottom:1px solid var(--line)}.chain span{grid-row:span 2;color:var(--teal);font-size:.74rem;font-weight:850}.chain h3{margin:0;color:var(--navy);font-size:1.08rem}.chain p{grid-column:2;margin:4px 0 0;color:var(--muted);font-size:.87rem}.release-section{display:grid;grid-template-columns:.7fr 1.3fr;gap:65px;margin:0 -38px;padding:76px 38px;background:var(--navy);color:#fff}.release-section h2{color:#fff}.release-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}.release-grid article{margin:0;padding-right:16px;border-right:1px solid rgba(255,255,255,.17)}.release-grid article:last-child{border:0}.release-grid b{display:block;font-size:2.6rem;letter-spacing:-.07em}.release-grid h3{margin:2px 0 5px;font-size:.93rem}.release-grid p{margin:0;color:#b6c6da;font-size:.78rem;line-height:1.55}.report-cta{display:flex;justify-content:space-between;align-items:end;gap:30px;padding:83px 0 15px}.page-title{padding:76px 0 46px}.page-title-rich{max-width:780px}.page-title h1{font-size:clamp(2.8rem,6vw,4.9rem)}.page-title p{max-width:700px;color:var(--muted);font-size:1.02rem}.notice{border-left:3px solid var(--teal);background:var(--teal-soft);padding:13px 16px;color:var(--ink)!important;font-size:.87rem}.report-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.report-card{display:flex;min-height:285px;flex-direction:column;margin:0;padding:22px;border:1px solid var(--line);border-radius:15px;background:var(--panel);transition:.2s ease}.report-meta{display:flex;justify-content:space-between;color:var(--teal);font-size:.7rem;font-weight:850;letter-spacing:.08em}.report-card h2{margin:32px 0 7px;line-height:1.25;font-size:1.18rem}.report-card h2 a{text-decoration:none}.report-card>p{margin:0;color:var(--muted);font-size:.8rem}.report-score{display:flex;justify-content:space-between;align-items:end;margin-top:auto;padding-top:22px;border-top:1px solid var(--line)}.report-score span{color:var(--muted);font-size:.73rem}.report-score strong{color:var(--navy);font-size:1.35rem;letter-spacing:-.05em}.report-card .text-link{margin-top:12px;font-size:.8rem}.workflow-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}.workflow-grid article,.change-list li{margin:0;padding:20px;border:1px solid var(--line);background:var(--panel);border-radius:12px}.workflow-grid article>span,.change-list li>span{color:var(--teal);font-weight:900}.workflow-grid h3{margin:6px 0}.table-wrap{overflow-x:auto}.change-list{list-style:none;padding:0;display:grid;gap:10px}.change-list li>span{float:right}.change-list p{margin:6px 0 0}.paste-summary{font-size:1.1rem;font-weight:650;background:var(--navy);color:#fff;padding:20px;border-radius:12px}.deliverables{display:flex;flex-wrap:wrap;gap:10px}.deliverables span{border:1px solid var(--line);background:var(--panel);border-radius:999px;padding:8px 12px}section,article{margin-bottom:38px}table{border-collapse:collapse;width:100%;background:var(--panel)}th,td{border:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top}th{background:var(--mist)}.report-body{max-width:850px;background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:28px;overflow-wrap:anywhere}.citation{color:var(--teal);font-weight:800;text-decoration:none}.references{padding-left:20px}code{background:var(--mist);padding:2px 5px;border-radius:4px}@media(max-width:850px){.site-header{padding:18px 22px;align-items:flex-start;flex-direction:column}.hero-home,.story-grid,.release-section{grid-template-columns:1fr;gap:35px}.cards{grid-template-columns:repeat(2,1fr)}.release-section{margin:0 -22px;padding:58px 22px}.report-grid{grid-template-columns:repeat(2,1fr)}main{padding:0 22px 70px}.hero-home{padding:62px 0}.report-cta{align-items:start;flex-direction:column}footer{padding:24px 22px;flex-direction:column}.proof-panel{max-width:470px}}@media(max-width:540px){nav{gap:13px}.hero h1{font-size:3rem}.cards,.report-grid,.release-grid{grid-template-columns:1fr}.release-grid article{padding:0 0 17px;border-right:0;border-bottom:1px solid rgba(255,255,255,.17)}.release-grid article:last-child{border:0}.report-body{padding:18px}.boundary-note{align-items:flex-start}.card{min-height:auto}}
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
