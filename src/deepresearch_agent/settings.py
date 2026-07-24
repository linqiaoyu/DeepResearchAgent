from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Settings:
    storage_path: Path
    max_critic_iter: int = 3
    token_budget: int = 200_000
    default_depth: int = 2
    execution_mode: Literal["deterministic", "llm"] = "deterministic"
    llm_budget_cny: float = 3.0
    llm_ledger_path: Path = Path("data/runtime/llm_ledger.jsonl")
    llm_max_sub_questions: int = 3
    llm_max_queries_per_sub_question: int = 3
    as_of: date | None = None
    max_searches_per_run: int = 20
    tavily_raw_content_char_limit: int = 40_000
    demo_daily_llm_limit_cny: float = 5.0
    demo_guard_path: Path = Path("data/runtime/demo_guard.json")
    demo_job_path: Path = Path("data/runtime/demo_jobs.json")
    demo_queue_limit: int = 3
    demo_as_of: date = date(2026, 7, 9)
    tool_contract_enabled: bool = True
    injection_guard_enabled: bool = False
    run_manifest_enabled: bool = True
    runs_root: Path = Path("runs")
    context_packer_enabled: bool = False
    reporter_context_token_budget: int = 200_000
    structured_logging_enabled: bool = True
    config_fail_fast_enabled: bool = True
    structured_output_enabled: bool = True
    progressive_delivery_enabled: bool = False
    trajectory_record_enabled: bool = False
    branch_budget_enabled: bool = False
    branch_total_budget: int = 20
    branch_single_cap: int = 10
    research_loop_enabled: bool = False
    research_loop_max_iterations: int = 1
    research_loop_budget_ceiling: int = 20
    research_loop_no_progress_window: int = 2
    research_min_evidence_count: int = 2
    research_min_independent_domains: int = 2
    research_min_average_confidence: float = 0.7
    research_max_freshness_age_days: int = 365
    research_max_unresolved_critic_issues: int = 0
    prior_memory_enabled: bool = False
    prior_watch_confidence_threshold: float = 0.7

    @property
    def research_loop_active(self) -> bool:
        return (
            self.research_loop_enabled
            and self.research_loop_max_iterations > 1
        )


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    root = project_root()
    storage = Path(os.getenv("DEEPRESEARCH_STORAGE_PATH", "data/runtime/research.db"))
    if not storage.is_absolute():
        storage = root / storage
    ledger = Path(os.getenv("DEEPRESEARCH_LLM_LEDGER_PATH", "data/runtime/llm_ledger.jsonl"))
    if not ledger.is_absolute():
        ledger = root / ledger
    demo_guard = Path(os.getenv("DEEPRESEARCH_DEMO_GUARD_PATH", "data/runtime/demo_guard.json"))
    if not demo_guard.is_absolute():
        demo_guard = root / demo_guard
    demo_jobs = Path(os.getenv("DEEPRESEARCH_DEMO_JOB_PATH", "data/runtime/demo_jobs.json"))
    if not demo_jobs.is_absolute():
        demo_jobs = root / demo_jobs
    runs_root = Path(os.getenv("DEEPRESEARCH_RUNS_ROOT", "runs"))
    if not runs_root.is_absolute():
        runs_root = root / runs_root
    mode = os.getenv("DEEPRESEARCH_MODE", "deterministic")
    if mode not in {"deterministic", "llm"}:
        mode = "deterministic"
    as_of_value = os.getenv("DEEPRESEARCH_AS_OF", "").strip()
    as_of = date.fromisoformat(as_of_value) if as_of_value else None
    return Settings(
        storage_path=storage,
        max_critic_iter=int(os.getenv("DEEPRESEARCH_MAX_CRITIC_ITER", "3")),
        token_budget=int(os.getenv("DEEPRESEARCH_TOKEN_BUDGET", "200000")),
        execution_mode=mode,
        llm_budget_cny=float(os.getenv("DEEPRESEARCH_LLM_BUDGET_CNY", "3.0")),
        llm_ledger_path=ledger,
        llm_max_sub_questions=int(os.getenv("DEEPRESEARCH_LLM_MAX_SUB_QUESTIONS", "3")),
        llm_max_queries_per_sub_question=int(
            os.getenv("DEEPRESEARCH_LLM_MAX_QUERIES_PER_SUB_QUESTION", "3")
        ),
        as_of=as_of,
        max_searches_per_run=int(os.getenv("DEEPRESEARCH_MAX_SEARCHES_PER_RUN", "20")),
        tavily_raw_content_char_limit=int(os.getenv("DEEPRESEARCH_TAVILY_RAW_CONTENT_CHAR_LIMIT", "40000")),
        demo_daily_llm_limit_cny=float(os.getenv("DEEPRESEARCH_DEMO_DAILY_LLM_LIMIT_CNY", "5.0")),
        demo_guard_path=demo_guard,
        demo_job_path=demo_jobs,
        demo_queue_limit=int(os.getenv("DEEPRESEARCH_DEMO_QUEUE_LIMIT", "3")),
        demo_as_of=date.fromisoformat(os.getenv("DEEPRESEARCH_DEMO_AS_OF", "2026-07-09")),
        tool_contract_enabled=_env_flag("TOOL_CONTRACT_ENABLED", default=True),
        injection_guard_enabled=_env_flag("INJECTION_GUARD_ENABLED"),
        run_manifest_enabled=_env_flag("RUN_MANIFEST_ENABLED", default=True),
        runs_root=runs_root,
        context_packer_enabled=_env_flag("CONTEXT_PACKER_ENABLED"),
        reporter_context_token_budget=int(
            os.getenv("DEEPRESEARCH_REPORTER_CONTEXT_TOKEN_BUDGET", "200000")
        ),
        structured_logging_enabled=_env_flag("STRUCTURED_LOGGING_ENABLED", default=True),
        config_fail_fast_enabled=_env_flag("CONFIG_FAIL_FAST_ENABLED", default=True),
        structured_output_enabled=_env_flag("STRUCTURED_OUTPUT_ENABLED", default=True),
        progressive_delivery_enabled=_env_flag("PROGRESSIVE_DELIVERY_ENABLED"),
        trajectory_record_enabled=_env_flag("TRAJECTORY_RECORD_ENABLED"),
        branch_budget_enabled=_env_flag("BRANCH_BUDGET_ENABLED"),
        branch_total_budget=int(
            os.getenv("DEEPRESEARCH_BRANCH_TOTAL_BUDGET", "20")
        ),
        branch_single_cap=int(
            os.getenv("DEEPRESEARCH_BRANCH_SINGLE_CAP", "10")
        ),
        research_loop_enabled=_env_flag("RESEARCH_LOOP_ENABLED"),
        research_loop_max_iterations=int(
            os.getenv("DEEPRESEARCH_RESEARCH_LOOP_MAX_ITERATIONS", "1")
        ),
        research_loop_budget_ceiling=int(
            os.getenv("DEEPRESEARCH_RESEARCH_LOOP_BUDGET_CEILING", "20")
        ),
        research_loop_no_progress_window=int(
            os.getenv("DEEPRESEARCH_RESEARCH_LOOP_NO_PROGRESS_WINDOW", "2")
        ),
        research_min_evidence_count=int(
            os.getenv("DEEPRESEARCH_RESEARCH_MIN_EVIDENCE_COUNT", "2")
        ),
        research_min_independent_domains=int(
            os.getenv(
                "DEEPRESEARCH_RESEARCH_MIN_INDEPENDENT_DOMAINS",
                "2",
            )
        ),
        research_min_average_confidence=float(
            os.getenv(
                "DEEPRESEARCH_RESEARCH_MIN_AVERAGE_CONFIDENCE",
                "0.7",
            )
        ),
        research_max_freshness_age_days=int(
            os.getenv(
                "DEEPRESEARCH_RESEARCH_MAX_FRESHNESS_AGE_DAYS",
                "365",
            )
        ),
        research_max_unresolved_critic_issues=int(
            os.getenv(
                "DEEPRESEARCH_RESEARCH_MAX_UNRESOLVED_CRITIC_ISSUES",
                "0",
            )
        ),
        prior_memory_enabled=_env_flag("PRIOR_MEMORY_ENABLED"),
        prior_watch_confidence_threshold=float(
            os.getenv(
                "DEEPRESEARCH_PRIOR_WATCH_CONFIDENCE_THRESHOLD",
                "0.7",
            )
        ),
    )


def configure_langsmith_from_env() -> bool:
    """Enable LangSmith tracing only when credentials are explicitly present."""
    if not os.getenv("LANGSMITH_API_KEY"):
        return False
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    return True
