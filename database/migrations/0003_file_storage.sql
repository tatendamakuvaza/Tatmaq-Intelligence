-- =============================================================================
-- Files kept in the database (STORAGE_BACKEND=database).
--
-- For hosts whose disk is wiped on restart, when no separate file store is wanted.
-- A file is one row in stored_files plus its content in pieces of at most 1 MB, so
-- neither the API nor PostgreSQL ever holds a whole file in memory.
--
-- These tables are not part of the tenant schema and get no Row Level Security
-- policy: RLS is enabled and nothing is granted, so the role that end-user requests
-- run as cannot read or write them at all (database/policies revokes everything on
-- every migrate). Files are reached through the API's signed links and by the
-- worker, which checks the organisation at the start of the key.
--
-- With the other storage backends these tables simply stay empty.
-- =============================================================================

CREATE TABLE stored_files (
    key TEXT PRIMARY KEY,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    content_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE stored_file_chunks (
    key TEXT NOT NULL REFERENCES stored_files (key) ON DELETE CASCADE,
    seq INTEGER NOT NULL CHECK (seq >= 0),
    data BYTEA NOT NULL,
    PRIMARY KEY (key, seq)
);

ALTER TABLE stored_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE stored_file_chunks ENABLE ROW LEVEL SECURITY;
