-- R122: give cross-run memory somewhere to live.
--
-- `EpisodicMemory` and `ProceduralMemory` both declare
-- `lifecycle = "cross_run"` and were plain in-process dicts. No table existed
-- in either backend, nothing wrote one, and the only production construction
-- site built an empty object per engine, so `PRIOR_MEMORY_ENABLED` and
-- `PROCEDURAL_MEMORY_ENABLED` could be switched on and read nothing.
--
-- The row is generic on purpose: a namespace, the key a reader queries by, an
-- id unique within that key, and an opaque payload. Storage does not import the
-- memory layer, so a new memory kind needs no new table and no second
-- implementation to drift.
CREATE TABLE IF NOT EXISTS memory_record (
    namespace TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    record_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (namespace, scope_key, record_id)
);
