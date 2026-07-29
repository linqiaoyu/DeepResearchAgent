from __future__ import annotations

from deepresearch_agent.settings import Settings, project_root
from deepresearch_agent.storage.postgres_store import PostgresStore
from deepresearch_agent.storage.protocol import StorageProtocol
from deepresearch_agent.storage.sqlite_store import SQLiteStore


def build_store(settings: Settings) -> StorageProtocol:
    """Choose a persistence adapter only at the application composition root."""

    if settings.storage_backend == "sqlite":
        return SQLiteStore(settings.storage_path)
    if not settings.postgres_dsn:
        raise ValueError("DEEPRESEARCH_POSTGRES_DSN is required for storage_backend=postgres")
    return PostgresStore(
        settings.postgres_dsn,
        migrations_dir=project_root() / "migrations",
    )
