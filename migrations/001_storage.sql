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
