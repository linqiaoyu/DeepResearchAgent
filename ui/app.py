from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    import streamlit as st
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("Streamlit is not installed. Run `pip install -e .` or use Docker Compose.") from exc


API_BASE_URL = os.getenv("DEEPRESEARCH_API_BASE_URL", "http://api:8000").rstrip("/")


def api_get(path: str) -> Any:
    try:
        with urllib.request.urlopen(f"{API_BASE_URL}{path}", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return local_asset(path)


def api_post(path: str, payload: dict[str, Any] | None = None, token: str | None = None) -> Any:
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if token:
        request.add_header("X-Demo-Owner-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
        except Exception:
            detail = str(exc)
        return {"error": detail, "status_code": exc.code}
    except Exception as exc:
        return {"error": str(exc), "status_code": 503}


def local_asset(path: str) -> Any:
    assets = json.loads((ROOT / "data" / "demo" / "g3_showcase.json").read_text(encoding="utf-8"))
    if path == "/demo":
        return {
            "name": "DeepResearchAgent public demo",
            "layers": ["showcase", "golden_rerun", "owner_live"],
            "showcase_report_count": len(assets["reports"]),
            "as_of": assets["as_of"],
            "methodology": assets["methodology"],
            "summary": assets["summary"],
            "guard": {},
            "langsmith": False,
        }
    if path == "/demo/reports":
        return [{key: value for key, value in item.items() if key != "report_markdown"} for item in assets["reports"]]
    if path.startswith("/demo/reports/"):
        report_id = path.rsplit("/", 1)[-1]
        for item in assets["reports"]:
            if item["id"] == report_id:
                return item
    if path == "/demo/methodology":
        return {
            "as_of": assets["as_of"],
            "methodology": assets["methodology"],
            "summary": assets["summary"],
        }
    if path == "/demo/questions":
        questions = json.loads((ROOT / "data" / "golden_set" / "v1" / "questions.json").read_text(encoding="utf-8"))
        return [
            {
                "id": item["id"],
                "topic": item["topic"],
                "type": item["type"],
                "difficulty": item["difficulty"],
                "false_premise": bool(item.get("false_premise", False)),
            }
            for item in questions["questions"]
        ]
    return {}


st.set_page_config(page_title="DeepResearchAgent Demo", layout="wide")
overview = api_get("/demo")

st.title("DeepResearchAgent")
st.caption("Finance deep-research demo with frozen Golden Set replay and owner-gated live search.")

summary = overview.get("summary", {})
cols = st.columns(5)
cols[0].metric("G3 composite", summary.get("avg_weighted_score", "n/a"))
cols[1].metric("Citation support", summary.get("avg_citation_support", "n/a"))
cols[2].metric("Resolution", summary.get("avg_citation_resolution_rate", "n/a"))
cols[3].metric("Repair retry", summary.get("avg_citation_repair_retry_rate", "n/a"))
cols[4].metric("As of", overview.get("as_of", "n/a"))

tab_showcase, tab_methodology, tab_rerun, tab_live = st.tabs(
    ["Showcase", "Methodology", "Golden rerun", "Owner live"]
)

with tab_showcase:
    reports = api_get("/demo/reports")
    options = {
        f"{item['id']} · {item['type']} · {item['topic'][:42]}": item["id"]
        for item in reports
    }
    selected = st.selectbox("Selected G3 report", list(options))
    report = api_get(f"/demo/reports/{options[selected]}")
    metric_cols = st.columns(5)
    for index, (label, key) in enumerate(
        [
            ("Weighted", "weighted_score"),
            ("Support rate", "citation_support_rate"),
            ("Resolution", "citation_resolution_rate"),
            ("Repair retry", "citation_repair_retry_rate"),
            ("Uncited", "uncited_claim_rate"),
        ]
    ):
        metric_cols[index].metric(label, report.get("metrics", {}).get(key, "n/a"))
    st.markdown(report.get("report_markdown", ""))

with tab_methodology:
    methodology = api_get("/demo/methodology")
    st.json(methodology)

with tab_rerun:
    questions = api_get("/demo/questions")
    labels = {f"{item['id']} · {item['type']} · {item['topic'][:58]}": item["id"] for item in questions}
    selected_question = st.selectbox("Golden question", list(labels))
    st.json(overview.get("guard", {}))
    if st.button("Run selected Golden case", type="primary"):
        with st.spinner("Running LLM pipeline over frozen-corpus replay"):
            result = api_post(f"/demo/rerun/{labels[selected_question]}")
        if "error" in result:
            st.error(result["error"])
        else:
            st.json({key: result.get(key) for key in ("research_id", "status", "cost_cny", "guard")})
            st.markdown(result.get("report", ""))

with tab_live:
    topic = st.text_area("Live topic", "宁德时代 2024 年业绩与欧洲工厂扩张研究")
    depth = st.slider("Depth", min_value=1, max_value=3, value=1)
    token = st.text_input("Owner token", type="password")
    if st.button("Run owner-gated live search"):
        with st.spinner("Running LLM pipeline with live search"):
            result = api_post("/demo/live", {"topic": topic, "depth_level": depth}, token=token)
        if "error" in result:
            st.error(result["error"])
        else:
            st.json({key: result.get(key) for key in ("research_id", "status", "cost_cny", "guard")})
            st.markdown(result.get("report", ""))
