-- =============================================================================
-- Multi-tenant security (specification section 3.4)
--
-- Company A must never see Company B's files, records, results or reports. Two
-- independent layers enforce that:
--
--   1. The API scopes every query to the caller's organisation.
--   2. This file. The API runs each end-user request as the database role
--      `tatmaq_app_user`, which has no access to any row except through the
--      policies below. A query that forgets its organisation filter returns
--      nothing from other tenants instead of leaking them.
--
-- Who is who
--   tatmaq_app_user    an end user acting through the API. Subject to every policy.
--   table owner        migrations and the background worker. Bypasses RLS, so the
--                      worker verifies each job's organisation itself.
--   anon/authenticated Supabase's browser-facing Data API roles. They get nothing:
--                      the web app talks only to our API, never straight to tables.
--
-- This file is idempotent and is re-applied on every migrate.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- The role the API assumes for end-user requests
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tatmaq_app_user') THEN
        CREATE ROLE tatmaq_app_user NOLOGIN NOINHERIT NOBYPASSRLS;
    END IF;
    -- Let the connecting role switch into it with SET LOCAL ROLE, without inheriting
    -- from it. PostgreSQL 16+ needs the SET option spelled out; superusers and roles
    -- that can already switch are left alone.
    IF current_setting('server_version_num')::INT >= 160000 THEN
        IF NOT pg_has_role(current_user, 'tatmaq_app_user', 'SET') THEN
            EXECUTE format('GRANT tatmaq_app_user TO %I WITH SET TRUE, INHERIT FALSE', current_user);
        END IF;
    ELSIF NOT pg_has_role(current_user, 'tatmaq_app_user', 'MEMBER') THEN
        EXECUTE format('GRANT tatmaq_app_user TO %I', current_user);
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO tatmaq_app_user;

-- ---------------------------------------------------------------------------
-- Helper functions
--
-- SECURITY DEFINER lets a policy look up memberships without the lookup itself
-- being filtered by the policy that is calling it. search_path is pinned so the
-- functions cannot be redirected to look-alike tables.
-- ---------------------------------------------------------------------------

-- The user the current request acts for (NULL when no user is set: deny by default).
CREATE OR REPLACE FUNCTION app_user_id()
RETURNS UUID
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT auth.uid();
$$;

-- Specification 3.4, extended: the organisation itself must also be active, so
-- suspending a customer cuts off access at the database.
CREATE OR REPLACE FUNCTION is_org_member(target_org UUID)
RETURNS BOOLEAN
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM organisation_memberships m
        JOIN organisations o ON o.id = m.organisation_id
        WHERE m.organisation_id = target_org
          AND m.user_id = auth.uid()
          AND m.status = 'active'
          AND o.status = 'active'
    );
$$;

CREATE OR REPLACE FUNCTION has_org_role(target_org UUID, allowed_roles TEXT[])
RETURNS BOOLEAN
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM organisation_memberships m
        JOIN organisations o ON o.id = m.organisation_id
        WHERE m.organisation_id = target_org
          AND m.user_id = auth.uid()
          AND m.status = 'active'
          AND o.status = 'active'
          AND m.role = ANY (allowed_roles)
    );
$$;

-- True when the given profile belongs to someone in one of the caller's organisations.
CREATE OR REPLACE FUNCTION shares_org_with(other_user UUID)
RETURNS BOOLEAN
LANGUAGE SQL
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM organisation_memberships mine
        JOIN organisation_memberships theirs ON theirs.organisation_id = mine.organisation_id
        WHERE mine.user_id = auth.uid()
          AND mine.status = 'active'
          AND theirs.user_id = other_user
    );
$$;

REVOKE ALL ON FUNCTION app_user_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION is_org_member(UUID) FROM PUBLIC;
REVOKE ALL ON FUNCTION has_org_role(UUID, TEXT[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION shares_org_with(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_user_id() TO tatmaq_app_user;
GRANT EXECUTE ON FUNCTION is_org_member(UUID) TO tatmaq_app_user;
GRANT EXECUTE ON FUNCTION has_org_role(UUID, TEXT[]) TO tatmaq_app_user;
GRANT EXECUTE ON FUNCTION shares_org_with(UUID) TO tatmaq_app_user;

-- ---------------------------------------------------------------------------
-- Privileges: start from nothing, then grant exactly what the API needs.
-- Nothing is deletable, and results, artifacts, agent history and usage are
-- read-only to end users: only the worker writes them.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    tenant_tables TEXT[] := ARRAY[
        'organisations', 'profiles', 'roles', 'organisation_memberships', 'workspaces',
        'datasets', 'dataset_versions', 'dataset_columns', 'analysis_jobs', 'agent_tasks',
        'agent_runs', 'analysis_results', 'artifacts', 'audit_logs', 'usage_records'];
    table_name TEXT;
    api_role TEXT;
BEGIN
    FOREACH table_name IN ARRAY tenant_tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON %I FROM PUBLIC, tatmaq_app_user', table_name);
        EXECUTE format('GRANT SELECT ON %I TO tatmaq_app_user', table_name);
        FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
                EXECUTE format('REVOKE ALL ON %I FROM %I', table_name, api_role);
            END IF;
        END LOOP;
    END LOOP;
END
$$;

-- Stored files (used when STORAGE_BACKEND=database) are not tenant tables: no end-user
-- role may touch them at all. They are reached through signed links and by the worker.
DO $$
DECLARE
    table_name TEXT;
    locked_out TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['stored_files', 'stored_file_chunks'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON %I FROM PUBLIC, tatmaq_app_user', table_name);
        FOREACH locked_out IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = locked_out) THEN
                EXECUTE format('REVOKE ALL ON %I FROM %I', table_name, locked_out);
            END IF;
        END LOOP;
    END LOOP;
END
$$;

GRANT INSERT ON profiles, workspaces, datasets, dataset_versions, analysis_jobs, audit_logs TO tatmaq_app_user;
-- Column-level UPDATE: an end-user request can rename things and request a
-- cancellation, but cannot rewrite a job's results, ownership or lock.
GRANT UPDATE (full_name, email, updated_at) ON profiles TO tatmaq_app_user;
GRANT UPDATE (name) ON workspaces TO tatmaq_app_user;
GRANT UPDATE (name, source_filename, file_type, status, error_message, updated_at) ON datasets TO tatmaq_app_user;
GRANT UPDATE (status, cancel_requested_at, completed_at, error_message, updated_at) ON analysis_jobs TO tatmaq_app_user;

-- ---------------------------------------------------------------------------
-- Policies. (DROP + CREATE keeps the file re-runnable.)
-- ---------------------------------------------------------------------------

-- organisations: members read. Creation goes through the API's system path,
-- because the creator is not yet a member of the organisation being created.
DROP POLICY IF EXISTS organisations_member_select ON organisations;
CREATE POLICY organisations_member_select ON organisations
    FOR SELECT TO tatmaq_app_user USING (is_org_member(id));

-- profiles: your own, plus colleagues in your organisations
DROP POLICY IF EXISTS profiles_visible_select ON profiles;
CREATE POLICY profiles_visible_select ON profiles
    FOR SELECT TO tatmaq_app_user USING (id = app_user_id() OR shares_org_with(id));
DROP POLICY IF EXISTS profiles_self_insert ON profiles;
CREATE POLICY profiles_self_insert ON profiles
    FOR INSERT TO tatmaq_app_user WITH CHECK (id = app_user_id());
DROP POLICY IF EXISTS profiles_self_update ON profiles;
CREATE POLICY profiles_self_update ON profiles
    FOR UPDATE TO tatmaq_app_user USING (id = app_user_id()) WITH CHECK (id = app_user_id());

-- roles: shared reference data
DROP POLICY IF EXISTS roles_read ON roles;
CREATE POLICY roles_read ON roles FOR SELECT TO tatmaq_app_user USING (TRUE);

-- memberships: your own, plus those of organisations you belong to
DROP POLICY IF EXISTS memberships_visible_select ON organisation_memberships;
CREATE POLICY memberships_visible_select ON organisation_memberships
    FOR SELECT TO tatmaq_app_user USING (user_id = app_user_id() OR is_org_member(organisation_id));

-- workspaces: members read; owners and admins create and rename
DROP POLICY IF EXISTS workspaces_member_select ON workspaces;
CREATE POLICY workspaces_member_select ON workspaces
    FOR SELECT TO tatmaq_app_user USING (is_org_member(organisation_id));
DROP POLICY IF EXISTS workspaces_admin_insert ON workspaces;
CREATE POLICY workspaces_admin_insert ON workspaces
    FOR INSERT TO tatmaq_app_user WITH CHECK (has_org_role(organisation_id, ARRAY['owner', 'admin']));
DROP POLICY IF EXISTS workspaces_admin_update ON workspaces;
CREATE POLICY workspaces_admin_update ON workspaces
    FOR UPDATE TO tatmaq_app_user
    USING (has_org_role(organisation_id, ARRAY['owner', 'admin']))
    WITH CHECK (has_org_role(organisation_id, ARRAY['owner', 'admin']));

-- datasets and versions: members read; owners, admins and analysts write
DROP POLICY IF EXISTS datasets_member_access ON datasets;
CREATE POLICY datasets_member_access ON datasets
    FOR SELECT TO tatmaq_app_user USING (is_org_member(organisation_id));
DROP POLICY IF EXISTS datasets_member_insert ON datasets;
CREATE POLICY datasets_member_insert ON datasets
    FOR INSERT TO tatmaq_app_user
    WITH CHECK (has_org_role(organisation_id, ARRAY['owner', 'admin', 'analyst']));
DROP POLICY IF EXISTS datasets_member_update ON datasets;
CREATE POLICY datasets_member_update ON datasets
    FOR UPDATE TO tatmaq_app_user
    USING (has_org_role(organisation_id, ARRAY['owner', 'admin', 'analyst']))
    WITH CHECK (has_org_role(organisation_id, ARRAY['owner', 'admin', 'analyst']));

DROP POLICY IF EXISTS dataset_versions_member_select ON dataset_versions;
CREATE POLICY dataset_versions_member_select ON dataset_versions
    FOR SELECT TO tatmaq_app_user USING (is_org_member(organisation_id));
DROP POLICY IF EXISTS dataset_versions_member_insert ON dataset_versions;
CREATE POLICY dataset_versions_member_insert ON dataset_versions
    FOR INSERT TO tatmaq_app_user
    WITH CHECK (has_org_role(organisation_id, ARRAY['owner', 'admin', 'analyst']));

DROP POLICY IF EXISTS dataset_columns_member_select ON dataset_columns;
CREATE POLICY dataset_columns_member_select ON dataset_columns
    FOR SELECT TO tatmaq_app_user USING (is_org_member(organisation_id));

-- analysis jobs: members read; owners, admins and analysts submit and cancel
DROP POLICY IF EXISTS analysis_jobs_member_select ON analysis_jobs;
CREATE POLICY analysis_jobs_member_select ON analysis_jobs
    FOR SELECT TO tatmaq_app_user USING (is_org_member(organisation_id));
DROP POLICY IF EXISTS analysis_jobs_member_insert ON analysis_jobs;
CREATE POLICY analysis_jobs_member_insert ON analysis_jobs
    FOR INSERT TO tatmaq_app_user
    WITH CHECK (has_org_role(organisation_id, ARRAY['owner', 'admin', 'analyst']));
DROP POLICY IF EXISTS analysis_jobs_member_update ON analysis_jobs;
CREATE POLICY analysis_jobs_member_update ON analysis_jobs
    FOR UPDATE TO tatmaq_app_user
    USING (has_org_role(organisation_id, ARRAY['owner', 'admin', 'analyst']))
    WITH CHECK (has_org_role(organisation_id, ARRAY['owner', 'admin', 'analyst']));

-- agent activity, findings and reports: read-only to members
DROP POLICY IF EXISTS agent_tasks_member_select ON agent_tasks;
CREATE POLICY agent_tasks_member_select ON agent_tasks
    FOR SELECT TO tatmaq_app_user USING (is_org_member(organisation_id));
DROP POLICY IF EXISTS agent_runs_member_select ON agent_runs;
CREATE POLICY agent_runs_member_select ON agent_runs
    FOR SELECT TO tatmaq_app_user USING (is_org_member(organisation_id));
DROP POLICY IF EXISTS analysis_results_member_select ON analysis_results;
CREATE POLICY analysis_results_member_select ON analysis_results
    FOR SELECT TO tatmaq_app_user USING (is_org_member(organisation_id));
DROP POLICY IF EXISTS artifacts_member_select ON artifacts;
CREATE POLICY artifacts_member_select ON artifacts
    FOR SELECT TO tatmaq_app_user USING (is_org_member(organisation_id));
DROP POLICY IF EXISTS usage_records_member_select ON usage_records;
CREATE POLICY usage_records_member_select ON usage_records
    FOR SELECT TO tatmaq_app_user USING (is_org_member(organisation_id));

-- audit log: append-only. Any member's action is recorded under their own id;
-- only owners and admins can read it; nobody can change or delete an entry.
DROP POLICY IF EXISTS audit_logs_admin_select ON audit_logs;
CREATE POLICY audit_logs_admin_select ON audit_logs
    FOR SELECT TO tatmaq_app_user USING (has_org_role(organisation_id, ARRAY['owner', 'admin']));
DROP POLICY IF EXISTS audit_logs_member_insert ON audit_logs;
CREATE POLICY audit_logs_member_insert ON audit_logs
    FOR INSERT TO tatmaq_app_user
    WITH CHECK (is_org_member(organisation_id) AND actor_id = app_user_id());
