-- =============================================================================
-- Built-in sign-in (AUTH_MODE=builtin, and AUTH_MODE=dev on a laptop).
--
-- The auth schema created by 000 started as a development stand-in for Supabase's.
-- It is also where the application keeps its own accounts when no outside sign-in
-- service is used, in production too. This file adds what that needs:
--
--   failed_sign_ins, locked_until   five wrong passwords in a row lock the account
--                                   for fifteen minutes
--   password_changed_at             when the password was last set
--
-- Like 000, this is applied only to a database whose auth schema is this project's
-- own. It is never applied to a Supabase project.
-- =============================================================================

ALTER TABLE auth.users
    ADD COLUMN failed_sign_ins INTEGER NOT NULL DEFAULT 0 CHECK (failed_sign_ins >= 0),
    ADD COLUMN locked_until TIMESTAMPTZ,
    ADD COLUMN password_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
