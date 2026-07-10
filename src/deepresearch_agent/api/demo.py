from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from deepresearch_agent.schemas import ResearchState
from deepresearch_agent.settings import Settings, load_settings, project_root
from deepresearch_agent.workflow import DeepResearchEngine


class DemoLimitExceeded(RuntimeError):
    pass


class DemoNotAuthorized(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoRunResult:
    research_id: str
    status: str
    report: str
    metrics: dict[str, Any] | None
    cost_cny: float
    guard: dict[str, Any]


class DailyCostGuard:
    def __init__(
        self,
        *,
        state_path: Path,
        limit_cny: float,
        today_func: Any = date.today,
    ) -> None:
        self.state_path = state_path
        self.limit_cny = limit_cny
        self._today = today_func
        self._lock = threading.Lock()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = self._load_current_state()
            return self._payload(state)

    def assert_can_start(self) -> None:
        with self._lock:
            state = self._load_current_state()
            if float(state["spent_cny"]) >= self.limit_cny:
                raise DemoLimitExceeded("Daily LLM demo budget has been reached.")

    def record_spend(self, cost_cny: float) -> dict[str, Any]:
        with self._lock:
            state = self._load_current_state()
            state["spent_cny"] = round(float(state["spent_cny"]) + max(0.0, cost_cny), 8)
            self._write_state(state)
            return self._payload(state)

    def _load_current_state(self) -> dict[str, Any]:
        today = self._today().isoformat()
        state = {"date": today, "spent_cny": 0.0}
        if self.state_path.exists():
            try:
                loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                loaded = {}
            if isinstance(loaded, dict) and loaded.get("date") == today:
                state["spent_cny"] = float(loaded.get("spent_cny", 0.0) or 0.0)
        self._write_state(state)
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _payload(self, state: dict[str, Any]) -> dict[str, Any]:
        spent = float(state["spent_cny"])
        return {
            "date": state["date"],
            "limit_cny": self.limit_cny,
            "spent_cny": round(spent, 8),
            "remaining_cny": round(max(0.0, self.limit_cny - spent), 8),
            "blocked": spent >= self.limit_cny,
        }


class DemoService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        root: Path | None = None,
        guard: DailyCostGuard | None = None,
    ) -> None:
        self.root = root or project_root()
        self.settings = settings or load_settings()
        self.assets_path = self.root / "data" / "demo" / "g3_showcase.json"
        self.questions_path = self.root / "data" / "golden_set" / "v1" / "questions.json"
        self.recording_dir = self.root / "data" / "recordings" / "golden_v1"
        self.runtime_dir = self.root / "data" / "runtime" / "demo"
        self.guard = guard or DailyCostGuard(
            state_path=self.settings.demo_guard_path,
            limit_cny=self.settings.demo_daily_llm_limit_cny,
        )
        self._run_lock = threading.Lock()

    def overview(self) -> dict[str, Any]:
        assets = self._assets()
        return {
            "name": "DeepResearchAgent public demo",
            "layers": ["showcase", "golden_rerun", "owner_live"],
            "showcase_report_count": len(assets["reports"]),
            "as_of": assets["as_of"],
            "methodology": assets["methodology"],
            "summary": assets["summary"],
            "guard": self.guard.snapshot(),
            "langsmith": bool(os.getenv("LANGSMITH_API_KEY")),
        }

    def reports(self) -> list[dict[str, Any]]:
        return [
            {
                key: value
                for key, value in item.items()
                if key != "report_markdown"
            }
            for item in self._assets()["reports"]
        ]

    def report(self, report_id: str) -> dict[str, Any]:
        for item in self._assets()["reports"]:
            if item["id"] == report_id:
                return item
        raise KeyError(report_id)

    def methodology(self) -> dict[str, Any]:
        assets = self._assets()
        return {
            "as_of": assets["as_of"],
            "methodology": assets["methodology"],
            "summary": assets["summary"],
        }

    def questions(self) -> list[dict[str, Any]]:
        questions = json.loads(self.questions_path.read_text(encoding="utf-8"))["questions"]
        return [
            {
                "id": item["id"],
                "topic": item["topic"],
                "type": item["type"],
                "difficulty": item["difficulty"],
                "false_premise": bool(item.get("false_premise", False)),
            }
            for item in questions
        ]

    def rerun_golden(self, question_id: str) -> DemoRunResult:
        question = self._question(question_id)
        return self._run_llm_pipeline(
            topic=question["topic"],
            depth_level=1,
            search_recording_mode="replay",
            search_provider="tavily",
            run_label=f"golden-{question_id}",
        )

    def run_live(self, *, topic: str, depth_level: int, owner_token: str | None) -> DemoRunResult:
        expected = os.getenv("DEMO_OWNER_TOKEN", "").strip()
        if not expected or owner_token != expected:
            raise DemoNotAuthorized("Owner token is required for live search.")
        return self._run_llm_pipeline(
            topic=topic,
            depth_level=depth_level,
            search_recording_mode="live",
            search_provider="tavily",
            run_label="owner-live",
        )

    def _run_llm_pipeline(
        self,
        *,
        topic: str,
        depth_level: int,
        search_recording_mode: str,
        search_provider: str,
        run_label: str,
    ) -> DemoRunResult:
        self.guard.assert_can_start()
        with self._run_lock:
            self.guard.assert_can_start()
            run_stamp = f"{run_label}-{int(time.time() * 1000)}"
            storage_path = self.runtime_dir / f"{run_stamp}.db"
            ledger_path = self.runtime_dir / "llm_ledger.jsonl"
            env = {
                "DEEPRESEARCH_MODE": "llm",
                "DEEPRESEARCH_SEARCH_PROVIDER": search_provider,
                "DEEPRESEARCH_SEARCH_RECORDING_MODE": search_recording_mode,
                "DEEPRESEARCH_SEARCH_RECORDING_DIR": str(self.recording_dir),
                "DEEPRESEARCH_STRUCTURED_DATA_PROVIDER": "fixture",
                "DEEPRESEARCH_STORAGE_PATH": str(storage_path),
                "DEEPRESEARCH_LLM_LEDGER_PATH": str(ledger_path),
                "DEEPRESEARCH_LLM_BUDGET_CNY": "3.0",
                "DEEPRESEARCH_AS_OF": self.settings.demo_as_of.isoformat(),
            }
            with _temporary_environ(env):
                state = DeepResearchEngine().run(topic=topic, depth_level=depth_level)
        cost_cny = _state_cost_cny(state)
        guard_payload = self.guard.record_spend(cost_cny)
        return DemoRunResult(
            research_id=state.research_id,
            status=state.status,
            report=state.final_report or "",
            metrics=state.evaluation.model_dump(mode="json") if state.evaluation else None,
            cost_cny=cost_cny,
            guard=guard_payload,
        )

    def _assets(self) -> dict[str, Any]:
        return json.loads(self.assets_path.read_text(encoding="utf-8"))

    def _question(self, question_id: str) -> dict[str, Any]:
        for item in json.loads(self.questions_path.read_text(encoding="utf-8"))["questions"]:
            if item["id"] == question_id:
                return item
        raise KeyError(question_id)


def _state_cost_cny(state: ResearchState) -> float:
    if state.evaluation and state.evaluation.cost_cny is not None:
        return float(state.evaluation.cost_cny)
    usage = state.metadata.get("llm_usage", {})
    if isinstance(usage, dict):
        return float(usage.get("total_cost_cny", 0.0) or 0.0)
    return 0.0


@contextmanager
def _temporary_environ(values: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
