-- =============================================================================
-- LOCAL DEVELOPMENT ONLY. Never applied to a Supabase project.
--
-- Supabase provides the `auth` schema (auth.users, auth.uid()). A plain PostgreSQL
-- server does not, so this file supplies the small part of it that the schema and
-- the Row Level Security policies depend on. scripts/migrate.py applies it only
-- when the database has no `auth` schema.
--
-- The comment on the schema is a marker: development sign-in refuses to run unless
-- it is present, so local accounts can never be written into a real Supabase
-- auth.users table.
-- =============================================================================

CREATE SCHEMA auth;
COMMENT ON SCHEMA auth IS 'tatmaq-local-auth-shim';

CREATE TABLE auth.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    encrypted_password TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Same definition Supabase uses: the id of the user the current request acts for,
-- taken from the JWT claims the API places on the transaction.
CREATE FUNCTION auth.uid() RETURNS UUID
LANGUAGE SQL
STABLE
AS $$
    SELECT COALESCE(
        NULLIF(current_setting('request.jwt.claim.sub', TRUE), ''),
        (NULLIF(current_setting('request.jwt.claims', TRUE), '')::JSONB ->> 'sub')
    )::UUID
$$;

-- The roles Supabase's Data API uses. They exist locally only so that the policies
-- file, which locks them out, behaves the same in both places.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
END
$$;
