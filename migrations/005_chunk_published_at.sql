ALTER TABLE chunk ADD COLUMN IF NOT EXISTS published_at TEXT NOT NULL DEFAULT '';
UPDATE chunk SET published_at = effective_date WHERE published_at = '';
CREATE INDEX IF NOT EXISTS idx_chunk_published_at ON chunk(published_at);
