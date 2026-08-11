-- Generated from migrations/*.sql; do not edit by hand.

-- 001_storage.sql
CREATE TABLE IF NOT EXISTS research_session (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    plan JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    sub_question_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'text',
    source_url TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_pub_date DATE,
    extract_text TEXT NOT NULL,
    structured_record_json JSONB,
    numeric_fields_json JSONB,
    numeric_fields_incomplete BOOLEAN NOT NULL DEFAULT false,
    source_tier TEXT NOT NULL DEFAULT 'unknown',
    content_truncated BOOLEAN NOT NULL DEFAULT false,
    bbox_json JSONB,
    confidence DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_research_position
    ON evidence(research_id, position, id);

CREATE TABLE IF NOT EXISTS evaluation_result (
    research_id TEXT PRIMARY KEY,
    result_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS document (
    id TEXT PRIMARY KEY,
    canonical_url TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_version (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    file_sha256 TEXT NOT NULL,
    effective_date DATE NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(document_id, file_sha256)
);

CREATE TABLE IF NOT EXISTS chunk (
    id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_version(id) ON DELETE CASCADE,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    page_number INTEGER,
    effective_date DATE NOT NULL,
    status TEXT NOT NULL,
    content TEXT NOT NULL,
    CHECK(char_end > char_start)
);

CREATE INDEX IF NOT EXISTS idx_chunk_document_span
    ON chunk(document_version_id, char_start, char_end);
CREATE INDEX IF NOT EXISTS idx_chunk_effective_date
    ON chunk(effective_date);

CREATE TABLE IF NOT EXISTS index_job (
    id TEXT PRIMARY KEY,
    index_version TEXT NOT NULL,
    status TEXT NOT NULL,
    checkpoint_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS retrieval_trace (
    id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL,
    index_version TEXT NOT NULL,
    trace_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 002_evidence_retrieval_ref.sql
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS retrieval_ref_json JSONB;

-- 003_chunk_bbox_index.sql
ALTER TABLE chunk ADD COLUMN IF NOT EXISTS bbox_index_json JSONB NOT NULL DEFAULT '[]'::jsonb;

-- 004_chunk_entity_id.sql
ALTER TABLE chunk ADD COLUMN IF NOT EXISTS entity_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_chunk_entity_id ON chunk(entity_id);

-- 005_chunk_published_at.sql
ALTER TABLE chunk ADD COLUMN IF NOT EXISTS published_at TEXT NOT NULL DEFAULT '';
UPDATE chunk SET published_at = effective_date WHERE published_at = '';
CREATE INDEX IF NOT EXISTS idx_chunk_published_at ON chunk(published_at);

-- 006_document_version_filing_date.sql
-- R112: close the one schema column that drifted between the two backends.
--
-- `document_version.filing_date` was added to the SQLite schema in R085 and
-- never written as a migration, so the Postgres `document_version` table simply
-- did not have it. The read path avoided a SQL error by not selecting the
-- column, which turned a schema gap into a silently empty disclosure date.
ALTER TABLE document_version ADD COLUMN IF NOT EXISTS filing_date TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_document_version_filing_date ON document_version(filing_date);

-- 007_memory_record.sql
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

-- 008_document_disclosure_provenance.sql
-- R154: preserve the registry/source that established a filing date.
-- A date without its provenance cannot demonstrate that it was not substituted
-- from the report period or retrieval time.
ALTER TABLE document_version ADD COLUMN IF NOT EXISTS published_at_source TEXT NOT NULL DEFAULT '';

