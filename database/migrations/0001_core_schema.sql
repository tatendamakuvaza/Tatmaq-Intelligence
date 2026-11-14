-- =============================================================================
-- TATMAQ Intelligence - core schema (specification v1.0, section 3.3)
--
-- The fifteen foundational tables, as specified. Hardening (status constraints,
-- tenant-aware foreign keys, operational columns, indexes) follows in 0002 so that
-- this file stays recognisable against the specification.
--
-- gen_random_uuid() is built into PostgreSQL 13+, so the pgcrypto extension named
-- in the specification is not required.
-- =============================================================================

-- 1. CUSTOMER ORGANISATIONS
CREATE TABLE organisations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    status VARCHAR(30) DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. USER PROFILES (one per Supabase Auth user)
CREATE TABLE profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id),
    full_name VARCHAR(200),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 15. ROLES (created early: memberships reference it)
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) UNIQUE NOT NULL,
    permissions JSONB NOT NULL DEFAULT '{}'
);

-- 3. ORGANISATION MEMBERS
CREATE TABLE organisation_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    user_id UUID NOT NULL REFERENCES profiles(id),
    role VARCHAR(30) NOT NULL DEFAULT 'analyst',
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    UNIQUE (organisation_id, user_id)
);

-- 4. WORKSPACES
CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    name VARCHAR(200) NOT NULL,
    created_by UUID REFERENCES profiles(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. DATASETS
CREATE TABLE datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    name VARCHAR(255) NOT NULL,
    source_filename VARCHAR(255),
    file_type VARCHAR(30),
    status VARCHAR(30) DEFAULT 'uploaded',
    created_by UUID REFERENCES profiles(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. DATASET VERSIONS
CREATE TABLE dataset_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    dataset_id UUID NOT NULL REFERENCES datasets(id),
    version_number INTEGER NOT NULL,
    storage_path TEXT NOT NULL,
    canonical_path TEXT,
    sha256_hash VARCHAR(64),
    row_count BIGINT,
    schema_json JSONB,
    profile_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (dataset_id, version_number)
);

-- 7. DATASET COLUMNS
CREATE TABLE dataset_columns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_version_id UUID NOT NULL
        REFERENCES dataset_versions(id),
    column_name VARCHAR(255) NOT NULL,
    data_type VARCHAR(50),
    inferred_role VARCHAR(50),
    null_count BIGINT DEFAULT 0,
    distinct_count BIGINT,
    metadata JSONB DEFAULT '{}'
);

-- 8. ANALYSIS JOBS
CREATE TABLE analysis_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    dataset_version_id UUID REFERENCES dataset_versions(id),
    requested_by UUID REFERENCES profiles(id),
    prompt TEXT NOT NULL,
    status VARCHAR(30) DEFAULT 'queued',
    priority INTEGER DEFAULT 5,
    idempotency_key VARCHAR(150),
    result_summary JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    UNIQUE (organisation_id, idempotency_key)
);

-- 9. AGENT TASKS
CREATE TABLE agent_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    job_id UUID NOT NULL REFERENCES analysis_jobs(id),
    agent_key VARCHAR(100) NOT NULL,
    task_input JSONB NOT NULL DEFAULT '{}',
    dependencies JSONB DEFAULT '[]',
    status VARCHAR(30) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 10. AGENT EXECUTION HISTORY
CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    task_id UUID NOT NULL REFERENCES agent_tasks(id),
    agent_key VARCHAR(100) NOT NULL,
    model_name VARCHAR(150),
    input_json JSONB,
    output_json JSONB,
    status VARCHAR(30) DEFAULT 'running',
    tokens_input BIGINT DEFAULT 0,
    tokens_output BIGINT DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- 11. ANALYSIS RESULTS
CREATE TABLE analysis_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    job_id UUID NOT NULL REFERENCES analysis_jobs(id),
    result_type VARCHAR(100),
    finding TEXT,
    evidence_json JSONB DEFAULT '{}',
    confidence NUMERIC(5,4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 12. ARTIFACTS
CREATE TABLE artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    job_id UUID NOT NULL REFERENCES analysis_jobs(id),
    artifact_type VARCHAR(50),
    storage_path TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 13. AUDIT LOGS
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    actor_id UUID,
    action VARCHAR(150) NOT NULL,
    resource_type VARCHAR(100),
    resource_id UUID,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 14. USAGE RECORDS
CREATE TABLE usage_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id UUID NOT NULL REFERENCES organisations(id),
    job_id UUID REFERENCES analysis_jobs(id),
    metric VARCHAR(100) NOT NULL,
    quantity NUMERIC(18,4) NOT NULL,
    unit VARCHAR(50),
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);
