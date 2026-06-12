from __future__ import annotations

import os
from dataclasses import dataclass
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


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_settings() -> Settings:
    root = project_root()
    storage = Path(os.getenv("DEEPRESEARCH_STORAGE_PATH", "data/runtime/research.db"))
    if not storage.is_absolute():
        storage = root / storage
    ledger = Path(os.getenv("DEEPRESEARCH_LLM_LEDGER_PATH", "data/runtime/llm_ledger.jsonl"))
    if not ledger.is_absolute():
        ledger = root / ledger
    mode = os.getenv("DEEPRESEARCH_MODE", "deterministic")
    if mode not in {"deterministic", "llm"}:
        mode = "deterministic"
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
    )
