from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    import streamlit as st
except ModuleNotFoundError as exc:  # pragma: no cover
    raise SystemExit("Streamlit is not installed. Run `pip install -e .` or use Docker Compose.") from exc

from deepresearch_agent.workflow import DeepResearchEngine


st.set_page_config(page_title="DeepResearchAgent", layout="wide")
st.title("DeepResearchAgent")

topic = st.text_input("Research topic", "AI Agent 在财富管理行业的落地机会研究")
depth = st.slider("Depth", min_value=1, max_value=3, value=2)

if st.button("Run research", type="primary"):
    with st.spinner("Planner -> Researchers -> Extractor -> Critic -> Reporter -> Evaluator"):
        state = DeepResearchEngine().run(topic=topic, depth_level=depth)
    st.session_state["state"] = state

state = st.session_state.get("state")
if state:
    metric_cols = st.columns(5)
    if state.evaluation:
        metric_cols[0].metric("Citation accuracy", state.evaluation.citation_accuracy)
        metric_cols[1].metric("Faithfulness", state.evaluation.faithfulness)
        metric_cols[2].metric("Relevance", state.evaluation.answer_relevance)
        metric_cols[3].metric("Cost", f"${state.evaluation.cost_usd:.4f}")
        metric_cols[4].metric("Latency", f"{state.evaluation.latency_seconds:.2f}s")

    tab_report, tab_evidence, tab_critic = st.tabs(["Report", "Evidence Store", "Critic"])
    with tab_report:
        st.markdown(state.final_report or "")
    with tab_evidence:
        st.dataframe(
            [
                {
                    "claim_type": item.claim_type,
                    "claim": item.claim,
                    "source": item.source_title,
                    "url": item.source_url,
                    "confidence": item.confidence,
                }
                for item in state.evidence_store
            ],
            use_container_width=True,
        )
    with tab_critic:
        if state.critic_report:
            st.json(state.critic_report.model_dump(mode="json"))

