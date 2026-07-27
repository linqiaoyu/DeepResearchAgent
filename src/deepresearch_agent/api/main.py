from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import BaseModel, Field

from deepresearch_agent.api.demo import DemoLimitExceeded, DemoNotAuthorized, DemoQueueFull, DemoService
from deepresearch_agent.schemas import ResearchRequest, ResearchResponse
from deepresearch_agent.settings import configure_langsmith_from_env
from deepresearch_agent.workflow import DeepResearchEngine

try:
    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.responses import JSONResponse
except ModuleNotFoundError:  # Local bare runtime can still use CLI/tests.
    FastAPI = None
    Header = None
    HTTPException = None
    Request = None
    JSONResponse = None


configure_langsmith_from_env()
engine = DeepResearchEngine()
demo_service = DemoService()


class OperationalState:
    def __init__(self) -> None:
        self.accepting = True
        self._inflight = 0
        self._lock = threading.Lock()

    @property
    def inflight(self) -> int:
        with self._lock:
            return self._inflight

    def enter(self) -> None:
        with self._lock:
            self._inflight += 1

    def exit(self) -> None:
        with self._lock:
            self._inflight = max(0, self._inflight - 1)

    def begin_shutdown(self) -> None:
        self.accepting = False

    async def wait_for_drain(self, timeout_s: float = 30.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while self.inflight and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)
        return self.inflight == 0


operational_state = OperationalState()


@asynccontextmanager
async def lifespan(_app: object) -> AsyncIterator[None]:
    operational_state.accepting = True
    yield
    operational_state.begin_shutdown()
    await operational_state.wait_for_drain()


class DemoLiveRequest(BaseModel):
    topic: str
    depth_level: int = Field(default=1, ge=1, le=3)


def run_research(request: ResearchRequest) -> ResearchResponse:
    reservation = 0.0
    if engine.settings.execution_mode == "llm":
        reservation = demo_service.guard.reserve(engine.settings.llm_budget_cny)
    try:
        # A request owns its workflow instance.  The module-level engine is a
        # read-model for checkpoints and metrics; sharing it for execution
        # would serialize every request behind its run-scoped safety lock.
        with DeepResearchEngine(settings=engine.settings) as request_engine:
            state = request_engine.run(
                topic=request.topic,
                depth_level=request.depth_level,
            )
    except Exception:
        if reservation:
            demo_service.guard.settle(reservation, reservation)
        raise
    if reservation:
        from deepresearch_agent.api.demo import _state_cost_cny
        demo_service.guard.settle(reservation, _state_cost_cny(state))
    return ResearchResponse(
        research_id=state.research_id,
        status=state.status,
        current_phase=state.current_phase,
        report_url=f"/research/{state.research_id}/report",
        metrics=state.evaluation,
    )


def _require_owner_token(token: str | None) -> None:
    expected = os.getenv("DEMO_OWNER_TOKEN", "").strip()
    if not expected or token != expected:
        raise HTTPException(status_code=403, detail="Owner token is required.")


if FastAPI is not None:
    app = FastAPI(
        title="DeepResearchAgent",
        description="Multi-agent deep research with Evidence Store, Critic, checkpointing, and evaluation harness.",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def track_inflight(request: Request, call_next):
        if request.url.path not in {"/health", "/healthz", "/readyz"}:
            if not operational_state.accepting:
                return JSONResponse(
                    status_code=503,
                    content={"status": "not_ready", "reason": "shutting_down"},
                )
        operational_state.enter()
        try:
            return await call_next(request)
        finally:
            operational_state.exit()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        if not operational_state.accepting:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "shutting_down"},
            )
        return {"status": "ready"}

    @app.post("/research", response_model=ResearchResponse)
    def create_research(
        request: ResearchRequest,
        x_demo_owner_token: str | None = Header(default=None),
    ) -> ResearchResponse:
        _require_owner_token(x_demo_owner_token)
        return run_research(request)

    @app.get("/research/{research_id}")
    def get_research(research_id: str, x_demo_owner_token: str | None = Header(default=None)) -> dict:
        _require_owner_token(x_demo_owner_token)
        state = engine.load_state(research_id)
        if not state:
            raise HTTPException(status_code=404, detail="research_id not found")
        return state.model_dump(mode="json")

    @app.get("/research/{research_id}/report")
    def get_report(research_id: str, x_demo_owner_token: str | None = Header(default=None)) -> dict[str, str]:
        _require_owner_token(x_demo_owner_token)
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
    def demo_rerun(question_id: str, x_demo_owner_token: str | None = Header(default=None)) -> dict:
        _require_owner_token(x_demo_owner_token)
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
