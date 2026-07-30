ALTER TABLE chunk ADD COLUMN IF NOT EXISTS entity_id TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_chunk_entity_id ON chunk(entity_id);
