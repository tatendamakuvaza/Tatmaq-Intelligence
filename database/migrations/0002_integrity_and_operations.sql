-- =============================================================================
-- Hardening promised in specification section 3.3: "indexes, stricter status
-- constraints, foreign-key ownership checks, composite tenant-aware relationships".
-- Also adds the columns the job queue, uploads and reports need to operate.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Organisations: locale defaults used when reading and presenting data
-- ---------------------------------------------------------------------------
ALTER TABLE organisations
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL,
    ADD COLUMN default_currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    ADD COLUMN timezone VARCHAR(64) NOT NULL DEFAULT 'Africa/Harare',
    ADD COLUMN date_order VARCHAR(3) NOT NULL DEFAULT 'DMY',
    ADD CONSTRAINT organisations_status_check CHECK (status IN ('active', 'suspended', 'closed')),
    ADD CONSTRAINT organisations_date_order_check CHECK (date_order IN ('DMY', 'MDY')),
    ADD CONSTRAINT organisations_slug_format CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$');

ALTER TABLE profiles
    ADD COLUMN email VARCHAR(320),
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

ALTER TABLE roles
    ADD COLUMN description TEXT;

ALTER TABLE organisation_memberships
    ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD CONSTRAINT organisation_memberships_role_fkey FOREIGN KEY (role) REFERENCES roles (name),
    ADD CONSTRAINT organisation_memberships_status_check CHECK (status IN ('active', 'invited', 'suspended'));

-- ---------------------------------------------------------------------------
-- Tenant-aware keys. Each parent gets UNIQUE (organisation_id, id) so that a child
-- can reference (organisation_id, parent_id) together. The database then refuses,
-- for example, a dataset in organisation A that points at a workspace in
-- organisation B, whatever the application code does.
-- ---------------------------------------------------------------------------
ALTER TABLE workspaces
    ADD CONSTRAINT workspaces_org_id_key UNIQUE (organisation_id, id),
    ADD CONSTRAINT workspaces_org_name_key UNIQUE (organisation_id, name);

ALTER TABLE datasets
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN status SET DEFAULT 'pending_upload',
    ADD COLUMN error_message TEXT,
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD CONSTRAINT datasets_org_id_key UNIQUE (organisation_id, id),
    ADD CONSTRAINT datasets_workspace_tenant_fkey
        FOREIGN KEY (organisation_id, workspace_id) REFERENCES workspaces (organisation_id, id),
    ADD CONSTRAINT datasets_status_check
        CHECK (status IN ('pending_upload', 'processing', 'ready', 'failed')),
    ADD CONSTRAINT datasets_file_type_check CHECK (file_type IS NULL OR file_type IN ('xlsx', 'csv'));

ALTER TABLE dataset_versions
    ADD COLUMN status VARCHAR(30) NOT NULL DEFAULT 'processing',
    ADD COLUMN size_bytes BIGINT,
    ADD COLUMN column_count INTEGER,
    ADD COLUMN cleaned_path TEXT,
    ADD COLUMN cleaning_json JSONB,
    ADD COLUMN error_message TEXT,
    ADD COLUMN created_by UUID REFERENCES profiles (id),
    ADD CONSTRAINT dataset_versions_org_id_key UNIQUE (organisation_id, id),
    ADD CONSTRAINT dataset_versions_storage_path_key UNIQUE (storage_path),
    ADD CONSTRAINT dataset_versions_dataset_tenant_fkey
        FOREIGN KEY (organisation_id, dataset_id) REFERENCES datasets (organisation_id, id),
    ADD CONSTRAINT dataset_versions_status_check CHECK (status IN ('processing', 'ready', 'failed')),
    ADD CONSTRAINT dataset_versions_number_check CHECK (version_number >= 1),
    ADD CONSTRAINT dataset_versions_hash_check CHECK (sha256_hash IS NULL OR sha256_hash ~ '^[0-9a-f]{64}$'),
    -- a version is only usable once both the cleaned data and its profile exist
    ADD CONSTRAINT dataset_versions_ready_is_complete CHECK (
        status <> 'ready'
        OR (canonical_path IS NOT NULL AND cleaned_path IS NOT NULL
            AND profile_json IS NOT NULL AND sha256_hash IS NOT NULL)
    );

ALTER TABLE dataset_columns
    ADD COLUMN organisation_id UUID NOT NULL REFERENCES organisations (id),
    ADD COLUMN position INTEGER NOT NULL DEFAULT 0,
    ADD CONSTRAINT dataset_columns_version_tenant_fkey
        FOREIGN KEY (organisation_id, dataset_version_id) REFERENCES dataset_versions (organisation_id, id),
    ADD CONSTRAINT dataset_columns_name_key UNIQUE (dataset_version_id, column_name);

-- ---------------------------------------------------------------------------
-- Analysis jobs double as the work queue (specification section 9.2)
-- ---------------------------------------------------------------------------
ALTER TABLE analysis_jobs
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN priority SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL,
    ADD COLUMN job_type VARCHAR(30) NOT NULL DEFAULT 'analysis',
    ADD COLUMN analysis_type VARCHAR(50) NOT NULL DEFAULT 'automatic',
    ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3,
    ADD COLUMN locked_by VARCHAR(100),
    ADD COLUMN lock_token UUID,
    ADD COLUMN heartbeat_at TIMESTAMPTZ,
    ADD COLUMN cancel_requested_at TIMESTAMPTZ,
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD CONSTRAINT analysis_jobs_org_id_key UNIQUE (organisation_id, id),
    ADD CONSTRAINT analysis_jobs_workspace_tenant_fkey
        FOREIGN KEY (organisation_id, workspace_id) REFERENCES workspaces (organisation_id, id),
    ADD CONSTRAINT analysis_jobs_version_tenant_fkey
        FOREIGN KEY (organisation_id, dataset_version_id) REFERENCES dataset_versions (organisation_id, id),
    ADD CONSTRAINT analysis_jobs_status_check CHECK (status IN (
        'queued', 'validating_dataset', 'planning', 'executing_agents',
        'quality_verification', 'generating_report',
        'completed', 'partially_completed', 'failed', 'cancelled')),
    ADD CONSTRAINT analysis_jobs_type_check CHECK (job_type IN ('ingestion', 'analysis')),
    ADD CONSTRAINT analysis_jobs_priority_check CHECK (priority BETWEEN 1 AND 9),
    ADD CONSTRAINT analysis_jobs_attempts_check CHECK (attempts >= 0 AND max_attempts >= 1),
    ADD CONSTRAINT analysis_jobs_prompt_length CHECK (char_length(prompt) BETWEEN 1 AND 4000);

ALTER TABLE agent_tasks
    ALTER COLUMN status SET NOT NULL,
    ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN action VARCHAR(100),
    ADD COLUMN started_at TIMESTAMPTZ,
    ADD COLUMN completed_at TIMESTAMPTZ,
    ADD CONSTRAINT agent_tasks_org_id_key UNIQUE (organisation_id, id),
    ADD CONSTRAINT agent_tasks_job_sequence_key UNIQUE (job_id, sequence),
    ADD CONSTRAINT agent_tasks_job_tenant_fkey
        FOREIGN KEY (organisation_id, job_id) REFERENCES analysis_jobs (organisation_id, id),
    ADD CONSTRAINT agent_tasks_status_check
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped', 'cancelled'));

ALTER TABLE agent_runs
    ALTER COLUMN status SET NOT NULL,
    ADD COLUMN job_id UUID NOT NULL REFERENCES analysis_jobs (id),
    ADD COLUMN attempt INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN duration_ms INTEGER,
    ADD CONSTRAINT agent_runs_task_tenant_fkey
        FOREIGN KEY (organisation_id, task_id) REFERENCES agent_tasks (organisation_id, id),
    ADD CONSTRAINT agent_runs_job_tenant_fkey
        FOREIGN KEY (organisation_id, job_id) REFERENCES analysis_jobs (organisation_id, id),
    ADD CONSTRAINT agent_runs_status_check CHECK (status IN ('running', 'completed', 'failed', 'cancelled'));

ALTER TABLE analysis_results
    ADD COLUMN agent_key VARCHAR(100),
    ADD COLUMN sequence INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN result_key VARCHAR(150),
    ADD COLUMN title VARCHAR(255),
    ADD COLUMN evidence_ref VARCHAR(50),
    ADD COLUMN approved BOOLEAN NOT NULL DEFAULT FALSE,
    ADD CONSTRAINT analysis_results_job_tenant_fkey
        FOREIGN KEY (organisation_id, job_id) REFERENCES analysis_jobs (organisation_id, id),
    ADD CONSTRAINT analysis_results_job_sequence_key UNIQUE (job_id, sequence),
    ADD CONSTRAINT analysis_results_confidence_check CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1);

ALTER TABLE artifacts
    ADD COLUMN title VARCHAR(255),
    ADD COLUMN filename VARCHAR(255),
    ADD COLUMN content_type VARCHAR(100),
    ADD COLUMN size_bytes BIGINT,
    ADD COLUMN sha256_hash VARCHAR(64),
    ADD CONSTRAINT artifacts_job_tenant_fkey
        FOREIGN KEY (organisation_id, job_id) REFERENCES analysis_jobs (organisation_id, id),
    ADD CONSTRAINT artifacts_job_type_key UNIQUE (job_id, artifact_type),
    ADD CONSTRAINT artifacts_type_check
        CHECK (artifact_type IN ('report_pdf', 'report_xlsx', 'report_html'));

-- One usage row per (metric, source): recording the same job twice cannot double-charge.
ALTER TABLE usage_records
    ADD COLUMN source_key VARCHAR(150),
    ADD CONSTRAINT usage_records_job_tenant_fkey
        FOREIGN KEY (organisation_id, job_id) REFERENCES analysis_jobs (organisation_id, id),
    ADD CONSTRAINT usage_records_source_key UNIQUE (organisation_id, metric, source_key),
    ADD CONSTRAINT usage_records_quantity_check CHECK (quantity >= 0);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX organisation_memberships_user_idx ON organisation_memberships (user_id) WHERE status = 'active';
CREATE INDEX datasets_workspace_idx ON datasets (organisation_id, workspace_id, created_at DESC);
CREATE INDEX dataset_columns_version_idx ON dataset_columns (dataset_version_id, position);
CREATE INDEX analysis_jobs_workspace_idx ON analysis_jobs (organisation_id, workspace_id, created_at DESC);
CREATE INDEX analysis_jobs_version_idx ON analysis_jobs (dataset_version_id);
-- the queue: what a worker scans to claim the next job
CREATE INDEX analysis_jobs_queue_idx ON analysis_jobs (priority, created_at) WHERE status = 'queued';
-- in-flight jobs: what the reaper scans to find workers that died
CREATE INDEX analysis_jobs_running_idx ON analysis_jobs (heartbeat_at)
    WHERE status IN ('validating_dataset', 'planning', 'executing_agents', 'quality_verification', 'generating_report');
CREATE INDEX agent_tasks_job_idx ON agent_tasks (job_id, sequence);
CREATE INDEX agent_runs_task_idx ON agent_runs (task_id, started_at);
CREATE INDEX agent_runs_job_idx ON agent_runs (organisation_id, job_id);
CREATE INDEX analysis_results_job_idx ON analysis_results (job_id, sequence);
CREATE INDEX artifacts_org_idx ON artifacts (organisation_id, created_at DESC);
CREATE INDEX audit_logs_org_idx ON audit_logs (organisation_id, created_at DESC);
CREATE INDEX usage_records_org_idx ON usage_records (organisation_id, recorded_at DESC);
