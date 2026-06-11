from __future__ import annotations

from deepresearch_agent.schemas import ResearchRequest, ResearchResponse
from deepresearch_agent.workflow import DeepResearchEngine

try:
    from fastapi import FastAPI, HTTPException
except ModuleNotFoundError:  # Local bare runtime can still use CLI/tests.
    FastAPI = None
    HTTPException = None


engine = DeepResearchEngine()


def run_research(request: ResearchRequest) -> ResearchResponse:
    state = engine.run(topic=request.topic, depth_level=request.depth_level)
    return ResearchResponse(
        research_id=state.research_id,
        status=state.status,
        current_phase=state.current_phase,
        report_url=f"/research/{state.research_id}/report",
        metrics=state.evaluation,
    )


if FastAPI is not None:
    app = FastAPI(
        title="DeepResearchAgent",
        description="Multi-agent deep research with Evidence Store, Critic, checkpointing, and evaluation harness.",
        version="0.1.0",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/research", response_model=ResearchResponse)
    def create_research(request: ResearchRequest) -> ResearchResponse:
        return run_research(request)

    @app.get("/research/{research_id}")
    def get_research(research_id: str) -> dict:
        state = engine.load_state(research_id)
        if not state:
            raise HTTPException(status_code=404, detail="research_id not found")
        return state.model_dump(mode="json")

    @app.get("/research/{research_id}/report")
    def get_report(research_id: str) -> dict[str, str]:
        state = engine.load_state(research_id)
        if not state:
            raise HTTPException(status_code=404, detail="research_id not found")
        return {"research_id": research_id, "report": state.final_report or ""}

    @app.get("/metrics")
    def metrics() -> list[dict]:
        return [item.model_dump(mode="json") for item in engine.store.latest_metrics()]
else:
    app = None
