-- R154: preserve the registry/source that established a filing date.
-- A date without its provenance cannot demonstrate that it was not substituted
-- from the report period or retrieval time.
ALTER TABLE document_version ADD COLUMN IF NOT EXISTS published_at_source TEXT NOT NULL DEFAULT '';
