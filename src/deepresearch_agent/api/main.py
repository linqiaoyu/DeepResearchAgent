from __future__ import annotations

from pydantic import BaseModel, Field

from deepresearch_agent.api.demo import DemoLimitExceeded, DemoNotAuthorized, DemoQueueFull, DemoService
from deepresearch_agent.schemas import ResearchRequest, ResearchResponse
from deepresearch_agent.settings import configure_langsmith_from_env
from deepresearch_agent.workflow import DeepResearchEngine

try:
    from fastapi import FastAPI, Header, HTTPException
except ModuleNotFoundError:  # Local bare runtime can still use CLI/tests.
    FastAPI = None
    Header = None
    HTTPException = None


configure_langsmith_from_env()
engine = DeepResearchEngine()
demo_service = DemoService()


class DemoLiveRequest(BaseModel):
    topic: str
    depth_level: int = Field(default=1, ge=1, le=3)


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

    @app.get("/demo")
    def demo_overview() -> dict:
        return demo_service.overview()

    @app.get("/demo/methodology")
    def demo_methodology() -> dict:
        return demo_service.methodology()

    @app.get("/demo/reports")
    def demo_reports() -> list[dict]:
        return demo_service.reports()

    @app.get("/demo/reports/{report_id}")
    def demo_report(report_id: str) -> dict:
        try:
            return demo_service.report(report_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="demo report not found") from None

    @app.get("/demo/questions")
    def demo_questions() -> list[dict]:
        return demo_service.questions()

    @app.post("/demo/rerun/{question_id}")
    def demo_rerun(question_id: str) -> dict:
        try:
            return demo_service.rerun_golden(question_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="golden question not found") from None
        except (DemoLimitExceeded, DemoQueueFull) as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from None

    @app.get("/demo/jobs/{job_id}")
    def demo_job(job_id: str) -> dict:
        try:
            return demo_service.job(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="demo job not found") from None

    @app.post("/demo/live")
    def demo_live(
        request: DemoLiveRequest,
        x_demo_owner_token: str | None = Header(default=None),
    ) -> dict:
        try:
            result = demo_service.run_live(
                topic=request.topic,
                depth_level=request.depth_level,
                owner_token=x_demo_owner_token,
            )
        except DemoNotAuthorized as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except DemoLimitExceeded as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from None
        return {
            "research_id": result.research_id,
            "status": result.status,
            "report": result.report,
            "metrics": result.metrics,
            "cost_cny": result.cost_cny,
            "guard": result.guard,
        }
else:
    app = None
