from __future__ import annotations

import os
import json
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path
from typing import Literal, get_type_hints

from deepresearch_agent.capability_rules import DEFAULT_CAPABILITY_RULES
from deepresearch_agent.llm_config import DASHSCOPE_RERANK_MODEL

DEFAULT_CAPABILITY_RULES_JSON = json.dumps(DEFAULT_CAPABILITY_RULES, ensure_ascii=False)


@dataclass(frozen=True)
class Settings:
    storage_path: Path
    storage_backend: Literal["sqlite", "postgres"] = "sqlite"
    postgres_dsn: str | None = None
    max_critic_iter: int = 3
    critic_enabled: bool = True
    extractor_enabled: bool = True
    token_budget: int = 200_000
    default_depth: int = 2
    execution_mode: Literal["deterministic", "llm"] = "deterministic"
    domain_pack: str = "finance"
    llm_budget_cny: float = 3.0
    llm_ledger_path: Path = Path("data/runtime/llm_ledger.jsonl")
    llm_max_sub_questions: int = 3
    llm_max_queries_per_sub_question: int = 3
    semantic_judge_enabled: bool = True
    as_of: date | None = None
    max_searches_per_run: int = 20
    max_external_search_requests_per_run: int = 20
    max_external_fetch_requests_per_run: int = 20
    # One disclosure operation may make up to three bounded attempts.  Each
    # attempt performs one announcement search plus at most one stock-list and
    # five PDF fetches, so the independent authority lane must cover the same
    # retry envelope.
    max_authority_search_requests_per_run: int = 3
    max_authority_fetch_requests_per_run: int = 18
    tavily_raw_content_char_limit: int = 40_000
    pdf_max_pages: int = 100
    # Corpus ingestion has a separate ceiling: public annual reports often
    # exceed the tool-fetch safeguard, but local ingestion remains bounded.
    rag_ingest_max_pages: int = 600
    demo_daily_llm_limit_cny: float = 5.0
    demo_guard_path: Path = Path("data/runtime/demo_guard.json")
    demo_job_path: Path = Path("data/runtime/demo_jobs.json")
    demo_queue_limit: int = 3
    demo_as_of: date = date(2026, 7, 9)
    tool_contract_enabled: bool = True
    injection_guard_enabled: bool = False
    run_manifest_enabled: bool = True
    runs_root: Path = Path("runs")
    context_packer_enabled: bool = True
    reporter_context_token_budget: int = 200_000
    structured_logging_enabled: bool = True
    config_fail_fast_enabled: bool = True
    structured_output_enabled: bool = True
    progressive_delivery_enabled: bool = False
    trajectory_record_enabled: bool = False
    branch_budget_enabled: bool = True
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
    decision_weaving_enabled: bool = True
    decision_weaving_budget_remaining_ratio: float = 0.2
    decision_weaving_verify_min_allocation: int = 1
    numeric_check_enabled: bool = True
    numeric_check_relative_tolerance: float = 0.01
    numeric_check_absolute_tolerance: float = 0.01
    dynamic_capability_enabled: bool = True
    llm_tool_selection_enabled: bool = False
    dynamic_capability_rules_json: str = DEFAULT_CAPABILITY_RULES_JSON
    reflection_enabled: bool = False
    # Round 033 real repeated-run ablation found no adopted strategy and no
    # causal behavior change.  Keep the experimental path opt-in until a
    # cross-run preference can beat the control on a registered task.
    procedural_memory_enabled: bool = False
    skill_packs_enabled: bool = False
    rag_enabled: bool = False
    rerank_enabled: bool = True
    rerank_fail_open: bool = True
    rerank_provider: str = "dashscope"
    rerank_model: str = DASHSCOPE_RERANK_MODEL
    retrieval_top_k: int = 50
    rerank_top_n: int = 8
    rag_budget_cny: float = 12.0

    @property
    def research_loop_active(self) -> bool:
        return (
            self.research_loop_enabled
            and self.research_loop_max_iterations > 1
        )


def boolean_setting_defaults() -> dict[str, bool]:
    """Return documented boolean flags directly from ``Settings`` defaults.

    Flag names intentionally follow the environment-variable convention used
    by ``load_settings``.  Discovery is type-driven so a newly added boolean
    setting cannot be silently omitted from generated documentation.
    """

    type_hints = get_type_hints(Settings)
    defaults = Settings(storage_path=Path("__settings_defaults__.db"))
    return {
        field.name.upper(): getattr(defaults, field.name)
        for field in fields(Settings)
        if type_hints.get(field.name) is bool
    }


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
    storage_backend = os.getenv("DEEPRESEARCH_STORAGE_BACKEND", "sqlite").strip().lower()
    if storage_backend not in {"sqlite", "postgres"}:
        raise ValueError("DEEPRESEARCH_STORAGE_BACKEND must be 'sqlite' or 'postgres'.")
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
    mode = os.getenv("DEEPRESEARCH_MODE", "deterministic").strip().lower()
    if mode not in {"deterministic", "llm"}:
        raise ValueError("DEEPRESEARCH_MODE must be 'deterministic' or 'llm'.")
    as_of_value = os.getenv("DEEPRESEARCH_AS_OF", "").strip()
    as_of = date.fromisoformat(as_of_value) if as_of_value else None
    return Settings(
        storage_path=storage,
        storage_backend=storage_backend,
        postgres_dsn=(
            os.getenv("DEEPRESEARCH_POSTGRES_DSN")
            or os.getenv("DEEPRESEARCH_PG_DSN")
            or None
        ),
        max_critic_iter=int(os.getenv("DEEPRESEARCH_MAX_CRITIC_ITER", "3")),
        critic_enabled=_env_flag("CRITIC_ENABLED", default=True),
        extractor_enabled=_env_flag("EXTRACTOR_ENABLED", default=True),
        token_budget=int(os.getenv("DEEPRESEARCH_TOKEN_BUDGET", "200000")),
        execution_mode=mode,
        domain_pack=os.getenv("DEEPRESEARCH_DOMAIN_PACK", "finance").strip(),
        llm_budget_cny=float(os.getenv("DEEPRESEARCH_LLM_BUDGET_CNY", "3.0")),
        llm_ledger_path=ledger,
        llm_max_sub_questions=int(os.getenv("DEEPRESEARCH_LLM_MAX_SUB_QUESTIONS", "3")),
        llm_max_queries_per_sub_question=int(
            os.getenv("DEEPRESEARCH_LLM_MAX_QUERIES_PER_SUB_QUESTION", "3")
        ),
        semantic_judge_enabled=_env_flag("SEMANTIC_JUDGE_ENABLED", default=True),
        as_of=as_of,
        max_searches_per_run=int(os.getenv("DEEPRESEARCH_MAX_SEARCHES_PER_RUN", "20")),
        max_external_search_requests_per_run=int(
            os.getenv("DEEPRESEARCH_MAX_EXTERNAL_SEARCH_REQUESTS_PER_RUN", "20")
        ),
        max_external_fetch_requests_per_run=int(
            os.getenv("DEEPRESEARCH_MAX_EXTERNAL_FETCH_REQUESTS_PER_RUN", "20")
        ),
        max_authority_search_requests_per_run=int(
            os.getenv(
                "DEEPRESEARCH_MAX_AUTHORITY_SEARCH_REQUESTS_PER_RUN",
                "3",
            )
        ),
        max_authority_fetch_requests_per_run=int(
            os.getenv(
                "DEEPRESEARCH_MAX_AUTHORITY_FETCH_REQUESTS_PER_RUN",
                "18",
            )
        ),
        tavily_raw_content_char_limit=int(os.getenv("DEEPRESEARCH_TAVILY_RAW_CONTENT_CHAR_LIMIT", "40000")),
        pdf_max_pages=int(os.getenv("DEEPRESEARCH_PDF_MAX_PAGES", "100")),
        rag_ingest_max_pages=int(os.getenv("RAG_INGEST_MAX_PAGES", "600")),
        demo_daily_llm_limit_cny=float(os.getenv("DEEPRESEARCH_DEMO_DAILY_LLM_LIMIT_CNY", "5.0")),
        demo_guard_path=demo_guard,
        demo_job_path=demo_jobs,
        demo_queue_limit=int(os.getenv("DEEPRESEARCH_DEMO_QUEUE_LIMIT", "3")),
        demo_as_of=date.fromisoformat(os.getenv("DEEPRESEARCH_DEMO_AS_OF", "2026-07-09")),
        tool_contract_enabled=_env_flag("TOOL_CONTRACT_ENABLED", default=True),
        injection_guard_enabled=_env_flag("INJECTION_GUARD_ENABLED"),
        run_manifest_enabled=_env_flag("RUN_MANIFEST_ENABLED", default=True),
        runs_root=runs_root,
        context_packer_enabled=_env_flag("CONTEXT_PACKER_ENABLED", default=True),
        reporter_context_token_budget=int(
            os.getenv("DEEPRESEARCH_REPORTER_CONTEXT_TOKEN_BUDGET", "200000")
        ),
        structured_logging_enabled=_env_flag("STRUCTURED_LOGGING_ENABLED", default=True),
        config_fail_fast_enabled=_env_flag("CONFIG_FAIL_FAST_ENABLED", default=True),
        structured_output_enabled=_env_flag("STRUCTURED_OUTPUT_ENABLED", default=True),
        progressive_delivery_enabled=_env_flag("PROGRESSIVE_DELIVERY_ENABLED"),
        trajectory_record_enabled=_env_flag("TRAJECTORY_RECORD_ENABLED"),
        branch_budget_enabled=_env_flag("BRANCH_BUDGET_ENABLED", default=True),
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
        decision_weaving_enabled=_env_flag("DECISION_WEAVING_ENABLED", default=True),
        decision_weaving_budget_remaining_ratio=float(
            os.getenv(
                "DEEPRESEARCH_DECISION_WEAVING_BUDGET_REMAINING_RATIO",
                "0.2",
            )
        ),
        decision_weaving_verify_min_allocation=int(
            os.getenv(
                "DEEPRESEARCH_DECISION_WEAVING_VERIFY_MIN_ALLOCATION",
                "1",
            )
        ),
        numeric_check_enabled=_env_flag("NUMERIC_CHECK_ENABLED", default=True),
        numeric_check_relative_tolerance=float(
            os.getenv(
                "DEEPRESEARCH_NUMERIC_CHECK_RELATIVE_TOLERANCE",
                "0.01",
            )
        ),
        numeric_check_absolute_tolerance=float(
            os.getenv(
                "DEEPRESEARCH_NUMERIC_CHECK_ABSOLUTE_TOLERANCE",
                "0.01",
            )
        ),
        dynamic_capability_enabled=_env_flag(
            "DYNAMIC_CAPABILITY_ENABLED", default=True
        ),
        llm_tool_selection_enabled=_env_flag("LLM_TOOL_SELECTION_ENABLED"),
        dynamic_capability_rules_json=os.getenv(
            "DEEPRESEARCH_DYNAMIC_CAPABILITY_RULES_JSON", DEFAULT_CAPABILITY_RULES_JSON
        ),
        reflection_enabled=_env_flag("REFLECTION_ENABLED"),
        procedural_memory_enabled=_env_flag(
            "PROCEDURAL_MEMORY_ENABLED",
        ),
        skill_packs_enabled=_env_flag("SKILL_PACKS_ENABLED"),
        rag_enabled=_env_flag("RAG_ENABLED"),
        rerank_enabled=_env_flag("RERANK_ENABLED", default=True),
        rerank_fail_open=_env_flag("RERANK_FAIL_OPEN", default=True),
        rerank_provider=os.getenv("RERANK_PROVIDER", "dashscope").strip(),
        rerank_model=os.getenv("RERANK_MODEL", DASHSCOPE_RERANK_MODEL).strip(),
        retrieval_top_k=int(os.getenv("RETRIEVAL_TOP_K", "50")),
        rerank_top_n=int(os.getenv("RERANK_TOP_N", "8")),
        rag_budget_cny=float(os.getenv("DEEPRESEARCH_RAG_BUDGET_CNY", "12.0")),
    )


def configure_langsmith_from_env() -> bool:
    """Enable LangSmith tracing only when credentials are explicitly present."""
    if not os.getenv("LANGSMITH_API_KEY"):
        return False
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    return True
