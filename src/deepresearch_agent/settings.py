from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    storage_path: Path
    max_critic_iter: int = 3
    token_budget: int = 200_000
    default_depth: int = 2


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_settings() -> Settings:
    root = project_root()
    storage = Path(os.getenv("DEEPRESEARCH_STORAGE_PATH", "data/runtime/research.db"))
    if not storage.is_absolute():
        storage = root / storage
    return Settings(
        storage_path=storage,
        max_critic_iter=int(os.getenv("DEEPRESEARCH_MAX_CRITIC_ITER", "3")),
        token_budget=int(os.getenv("DEEPRESEARCH_TOKEN_BUDGET", "200000")),
    )

