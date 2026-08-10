-- R112: close the one schema column that drifted between the two backends.
--
-- `document_version.filing_date` was added to the SQLite schema in R085 and
-- never written as a migration, so the Postgres `document_version` table simply
-- did not have it. The read path avoided a SQL error by not selecting the
-- column, which turned a schema gap into a silently empty disclosure date.
ALTER TABLE document_version ADD COLUMN IF NOT EXISTS filing_date TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_document_version_filing_date ON document_version(filing_date);
