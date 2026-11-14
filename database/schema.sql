-- =============================================================================
-- TATMAQ Intelligence - complete schema, for reference.
--
-- GENERATED: do not edit and do not apply. The schema is built by the files in
-- database/migrations (then policies, then seeds) through scripts/migrate.py.
-- This snapshot shows the result in one place: tables, constraints, indexes,
-- functions and Row Level Security policies.
-- Regenerate with:  pg_dump --schema-only --no-owner --no-privileges --schema=public
-- =============================================================================

--
-- PostgreSQL database dump
--
--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--
CREATE SCHEMA public;
--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--
COMMENT ON SCHEMA public IS 'standard public schema';
--
-- Name: app_user_id(); Type: FUNCTION; Schema: public; Owner: -
--
CREATE FUNCTION public.app_user_id() RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
    SELECT auth.uid();
$$;
--
-- Name: has_org_role(uuid, text[]); Type: FUNCTION; Schema: public; Owner: -
--
CREATE FUNCTION public.has_org_role(target_org uuid, allowed_roles text[]) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
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
--
-- Name: is_org_member(uuid); Type: FUNCTION; Schema: public; Owner: -
--
CREATE FUNCTION public.is_org_member(target_org uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
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
--
-- Name: shares_org_with(uuid); Type: FUNCTION; Schema: public; Owner: -
--
CREATE FUNCTION public.shares_org_with(other_user uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
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
--
-- Name: agent_runs; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.agent_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id uuid NOT NULL,
    task_id uuid NOT NULL,
    agent_key character varying(100) NOT NULL,
    model_name character varying(150),
    input_json jsonb,
    output_json jsonb,
    status character varying(30) DEFAULT 'running'::character varying NOT NULL,
    tokens_input bigint DEFAULT 0,
    tokens_output bigint DEFAULT 0,
    error_message text,
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone,
    job_id uuid NOT NULL,
    attempt integer DEFAULT 1 NOT NULL,
    duration_ms integer,
    CONSTRAINT agent_runs_status_check CHECK (((status)::text = ANY ((ARRAY['running'::character varying, 'completed'::character varying, 'failed'::character varying, 'cancelled'::character varying])::text[])))
);
--
-- Name: agent_tasks; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.agent_tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id uuid NOT NULL,
    job_id uuid NOT NULL,
    agent_key character varying(100) NOT NULL,
    task_input jsonb DEFAULT '{}'::jsonb NOT NULL,
    dependencies jsonb DEFAULT '[]'::jsonb,
    status character varying(30) DEFAULT 'pending'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    sequence integer DEFAULT 0 NOT NULL,
    action character varying(100),
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    CONSTRAINT agent_tasks_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying, 'skipped'::character varying, 'cancelled'::character varying])::text[])))
);
--
-- Name: analysis_jobs; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.analysis_jobs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    dataset_version_id uuid,
    requested_by uuid,
    prompt text NOT NULL,
    status character varying(30) DEFAULT 'queued'::character varying NOT NULL,
    priority integer DEFAULT 5 NOT NULL,
    idempotency_key character varying(150),
    result_summary jsonb,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    job_type character varying(30) DEFAULT 'analysis'::character varying NOT NULL,
    analysis_type character varying(50) DEFAULT 'automatic'::character varying NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 3 NOT NULL,
    locked_by character varying(100),
    lock_token uuid,
    heartbeat_at timestamp with time zone,
    cancel_requested_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT analysis_jobs_attempts_check CHECK (((attempts >= 0) AND (max_attempts >= 1))),
    CONSTRAINT analysis_jobs_priority_check CHECK (((priority >= 1) AND (priority <= 9))),
    CONSTRAINT analysis_jobs_prompt_length CHECK (((char_length(prompt) >= 1) AND (char_length(prompt) <= 4000))),
    CONSTRAINT analysis_jobs_status_check CHECK (((status)::text = ANY ((ARRAY['queued'::character varying, 'validating_dataset'::character varying, 'planning'::character varying, 'executing_agents'::character varying, 'quality_verification'::character varying, 'generating_report'::character varying, 'completed'::character varying, 'partially_completed'::character varying, 'failed'::character varying, 'cancelled'::character varying])::text[]))),
    CONSTRAINT analysis_jobs_type_check CHECK (((job_type)::text = ANY ((ARRAY['ingestion'::character varying, 'analysis'::character varying])::text[])))
);
--
-- Name: analysis_results; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.analysis_results (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id uuid NOT NULL,
    job_id uuid NOT NULL,
    result_type character varying(100),
    finding text,
    evidence_json jsonb DEFAULT '{}'::jsonb,
    confidence numeric(5,4),
    created_at timestamp with time zone DEFAULT now(),
    agent_key character varying(100),
    sequence integer DEFAULT 0 NOT NULL,
    result_key character varying(150),
    title character varying(255),
    evidence_ref character varying(50),
    approved boolean DEFAULT false NOT NULL,
    CONSTRAINT analysis_results_confidence_check CHECK (((confidence IS NULL) OR ((confidence >= (0)::numeric) AND (confidence <= (1)::numeric))))
);
--
-- Name: artifacts; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.artifacts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id uuid NOT NULL,
    job_id uuid NOT NULL,
    artifact_type character varying(50),
    storage_path text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now(),
    title character varying(255),
    filename character varying(255),
    content_type character varying(100),
    size_bytes bigint,
    sha256_hash character varying(64),
    CONSTRAINT artifacts_type_check CHECK (((artifact_type)::text = ANY ((ARRAY['report_pdf'::character varying, 'report_xlsx'::character varying, 'report_html'::character varying])::text[])))
);
--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.audit_logs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id uuid NOT NULL,
    actor_id uuid,
    action character varying(150) NOT NULL,
    resource_type character varying(100),
    resource_id uuid,
    details jsonb DEFAULT '{}'::jsonb,
    created_at timestamp with time zone DEFAULT now()
);
--
-- Name: dataset_columns; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.dataset_columns (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dataset_version_id uuid NOT NULL,
    column_name character varying(255) NOT NULL,
    data_type character varying(50),
    inferred_role character varying(50),
    null_count bigint DEFAULT 0,
    distinct_count bigint,
    metadata jsonb DEFAULT '{}'::jsonb,
    organisation_id uuid NOT NULL,
    "position" integer DEFAULT 0 NOT NULL
);
--
-- Name: dataset_versions; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.dataset_versions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id uuid NOT NULL,
    dataset_id uuid NOT NULL,
    version_number integer NOT NULL,
    storage_path text NOT NULL,
    canonical_path text,
    sha256_hash character varying(64),
    row_count bigint,
    schema_json jsonb,
    profile_json jsonb,
    created_at timestamp with time zone DEFAULT now(),
    status character varying(30) DEFAULT 'processing'::character varying NOT NULL,
    size_bytes bigint,
    column_count integer,
    cleaned_path text,
    cleaning_json jsonb,
    error_message text,
    created_by uuid,
    CONSTRAINT dataset_versions_hash_check CHECK (((sha256_hash IS NULL) OR ((sha256_hash)::text ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT dataset_versions_number_check CHECK ((version_number >= 1)),
    CONSTRAINT dataset_versions_ready_is_complete CHECK ((((status)::text <> 'ready'::text) OR ((canonical_path IS NOT NULL) AND (cleaned_path IS NOT NULL) AND (profile_json IS NOT NULL) AND (sha256_hash IS NOT NULL)))),
    CONSTRAINT dataset_versions_status_check CHECK (((status)::text = ANY ((ARRAY['processing'::character varying, 'ready'::character varying, 'failed'::character varying])::text[])))
);
--
-- Name: datasets; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.datasets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    source_filename character varying(255),
    file_type character varying(30),
    status character varying(30) DEFAULT 'pending_upload'::character varying NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now(),
    error_message text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT datasets_file_type_check CHECK (((file_type IS NULL) OR ((file_type)::text = ANY ((ARRAY['xlsx'::character varying, 'csv'::character varying])::text[])))),
    CONSTRAINT datasets_status_check CHECK (((status)::text = ANY ((ARRAY['pending_upload'::character varying, 'processing'::character varying, 'ready'::character varying, 'failed'::character varying])::text[])))
);
--
-- Name: organisation_memberships; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.organisation_memberships (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role character varying(30) DEFAULT 'analyst'::character varying NOT NULL,
    status character varying(30) DEFAULT 'active'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT organisation_memberships_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'invited'::character varying, 'suspended'::character varying])::text[])))
);
--
-- Name: organisations; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.organisations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(200) NOT NULL,
    slug character varying(100) NOT NULL,
    status character varying(30) DEFAULT 'active'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    default_currency character varying(3) DEFAULT 'USD'::character varying NOT NULL,
    timezone character varying(64) DEFAULT 'Africa/Harare'::character varying NOT NULL,
    date_order character varying(3) DEFAULT 'DMY'::character varying NOT NULL,
    CONSTRAINT organisations_date_order_check CHECK (((date_order)::text = ANY ((ARRAY['DMY'::character varying, 'MDY'::character varying])::text[]))),
    CONSTRAINT organisations_slug_format CHECK (((slug)::text ~ '^[a-z0-9]+(-[a-z0-9]+)*$'::text)),
    CONSTRAINT organisations_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'suspended'::character varying, 'closed'::character varying])::text[])))
);
--
-- Name: profiles; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.profiles (
    id uuid NOT NULL,
    full_name character varying(200),
    created_at timestamp with time zone DEFAULT now(),
    email character varying(320),
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);
--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.roles (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying(50) NOT NULL,
    permissions jsonb DEFAULT '{}'::jsonb NOT NULL,
    description text
);
--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.schema_migrations (
    filename text NOT NULL,
    checksum text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);
--
-- Name: stored_file_chunks; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.stored_file_chunks (
    key text NOT NULL,
    seq integer NOT NULL,
    data bytea NOT NULL,
    CONSTRAINT stored_file_chunks_seq_check CHECK ((seq >= 0))
);
--
-- Name: stored_files; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.stored_files (
    key text NOT NULL,
    size_bytes bigint NOT NULL,
    content_type text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT stored_files_size_bytes_check CHECK ((size_bytes >= 0))
);
--
-- Name: usage_records; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.usage_records (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id uuid NOT NULL,
    job_id uuid,
    metric character varying(100) NOT NULL,
    quantity numeric(18,4) NOT NULL,
    unit character varying(50),
    recorded_at timestamp with time zone DEFAULT now(),
    source_key character varying(150),
    CONSTRAINT usage_records_quantity_check CHECK ((quantity >= (0)::numeric))
);
--
-- Name: workspaces; Type: TABLE; Schema: public; Owner: -
--
CREATE TABLE public.workspaces (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organisation_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now()
);
--
-- Name: agent_runs agent_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_pkey PRIMARY KEY (id);
--
-- Name: agent_tasks agent_tasks_job_sequence_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_tasks
    ADD CONSTRAINT agent_tasks_job_sequence_key UNIQUE (job_id, sequence);
--
-- Name: agent_tasks agent_tasks_org_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_tasks
    ADD CONSTRAINT agent_tasks_org_id_key UNIQUE (organisation_id, id);
--
-- Name: agent_tasks agent_tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_tasks
    ADD CONSTRAINT agent_tasks_pkey PRIMARY KEY (id);
--
-- Name: analysis_jobs analysis_jobs_org_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT analysis_jobs_org_id_key UNIQUE (organisation_id, id);
--
-- Name: analysis_jobs analysis_jobs_organisation_id_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT analysis_jobs_organisation_id_idempotency_key_key UNIQUE (organisation_id, idempotency_key);
--
-- Name: analysis_jobs analysis_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT analysis_jobs_pkey PRIMARY KEY (id);
--
-- Name: analysis_results analysis_results_job_sequence_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_results
    ADD CONSTRAINT analysis_results_job_sequence_key UNIQUE (job_id, sequence);
--
-- Name: analysis_results analysis_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_results
    ADD CONSTRAINT analysis_results_pkey PRIMARY KEY (id);
--
-- Name: artifacts artifacts_job_type_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_job_type_key UNIQUE (job_id, artifact_type);
--
-- Name: artifacts artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (id);
--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);
--
-- Name: dataset_columns dataset_columns_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_columns
    ADD CONSTRAINT dataset_columns_name_key UNIQUE (dataset_version_id, column_name);
--
-- Name: dataset_columns dataset_columns_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_columns
    ADD CONSTRAINT dataset_columns_pkey PRIMARY KEY (id);
--
-- Name: dataset_versions dataset_versions_dataset_id_version_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT dataset_versions_dataset_id_version_number_key UNIQUE (dataset_id, version_number);
--
-- Name: dataset_versions dataset_versions_org_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT dataset_versions_org_id_key UNIQUE (organisation_id, id);
--
-- Name: dataset_versions dataset_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT dataset_versions_pkey PRIMARY KEY (id);
--
-- Name: dataset_versions dataset_versions_storage_path_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT dataset_versions_storage_path_key UNIQUE (storage_path);
--
-- Name: datasets datasets_org_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_org_id_key UNIQUE (organisation_id, id);
--
-- Name: datasets datasets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_pkey PRIMARY KEY (id);
--
-- Name: organisation_memberships organisation_memberships_organisation_id_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.organisation_memberships
    ADD CONSTRAINT organisation_memberships_organisation_id_user_id_key UNIQUE (organisation_id, user_id);
--
-- Name: organisation_memberships organisation_memberships_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.organisation_memberships
    ADD CONSTRAINT organisation_memberships_pkey PRIMARY KEY (id);
--
-- Name: organisations organisations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.organisations
    ADD CONSTRAINT organisations_pkey PRIMARY KEY (id);
--
-- Name: organisations organisations_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.organisations
    ADD CONSTRAINT organisations_slug_key UNIQUE (slug);
--
-- Name: profiles profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_pkey PRIMARY KEY (id);
--
-- Name: roles roles_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_name_key UNIQUE (name);
--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);
--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (filename);
--
-- Name: stored_file_chunks stored_file_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.stored_file_chunks
    ADD CONSTRAINT stored_file_chunks_pkey PRIMARY KEY (key, seq);
--
-- Name: stored_files stored_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.stored_files
    ADD CONSTRAINT stored_files_pkey PRIMARY KEY (key);
--
-- Name: usage_records usage_records_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_pkey PRIMARY KEY (id);
--
-- Name: usage_records usage_records_source_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_source_key UNIQUE (organisation_id, metric, source_key);
--
-- Name: workspaces workspaces_org_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_org_id_key UNIQUE (organisation_id, id);
--
-- Name: workspaces workspaces_org_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_org_name_key UNIQUE (organisation_id, name);
--
-- Name: workspaces workspaces_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_pkey PRIMARY KEY (id);
--
-- Name: agent_runs_job_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX agent_runs_job_idx ON public.agent_runs USING btree (organisation_id, job_id);
--
-- Name: agent_runs_task_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX agent_runs_task_idx ON public.agent_runs USING btree (task_id, started_at);
--
-- Name: agent_tasks_job_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX agent_tasks_job_idx ON public.agent_tasks USING btree (job_id, sequence);
--
-- Name: analysis_jobs_queue_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX analysis_jobs_queue_idx ON public.analysis_jobs USING btree (priority, created_at) WHERE ((status)::text = 'queued'::text);
--
-- Name: analysis_jobs_running_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX analysis_jobs_running_idx ON public.analysis_jobs USING btree (heartbeat_at) WHERE ((status)::text = ANY ((ARRAY['validating_dataset'::character varying, 'planning'::character varying, 'executing_agents'::character varying, 'quality_verification'::character varying, 'generating_report'::character varying])::text[]));
--
-- Name: analysis_jobs_version_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX analysis_jobs_version_idx ON public.analysis_jobs USING btree (dataset_version_id);
--
-- Name: analysis_jobs_workspace_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX analysis_jobs_workspace_idx ON public.analysis_jobs USING btree (organisation_id, workspace_id, created_at DESC);
--
-- Name: analysis_results_job_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX analysis_results_job_idx ON public.analysis_results USING btree (job_id, sequence);
--
-- Name: artifacts_org_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX artifacts_org_idx ON public.artifacts USING btree (organisation_id, created_at DESC);
--
-- Name: audit_logs_org_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX audit_logs_org_idx ON public.audit_logs USING btree (organisation_id, created_at DESC);
--
-- Name: dataset_columns_version_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX dataset_columns_version_idx ON public.dataset_columns USING btree (dataset_version_id, "position");
--
-- Name: datasets_workspace_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX datasets_workspace_idx ON public.datasets USING btree (organisation_id, workspace_id, created_at DESC);
--
-- Name: organisation_memberships_user_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX organisation_memberships_user_idx ON public.organisation_memberships USING btree (user_id) WHERE ((status)::text = 'active'::text);
--
-- Name: usage_records_org_idx; Type: INDEX; Schema: public; Owner: -
--
CREATE INDEX usage_records_org_idx ON public.usage_records USING btree (organisation_id, recorded_at DESC);
--
-- Name: agent_runs agent_runs_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.analysis_jobs(id);
--
-- Name: agent_runs agent_runs_job_tenant_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_job_tenant_fkey FOREIGN KEY (organisation_id, job_id) REFERENCES public.analysis_jobs(organisation_id, id);
--
-- Name: agent_runs agent_runs_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: agent_runs agent_runs_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.agent_tasks(id);
--
-- Name: agent_runs agent_runs_task_tenant_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_runs
    ADD CONSTRAINT agent_runs_task_tenant_fkey FOREIGN KEY (organisation_id, task_id) REFERENCES public.agent_tasks(organisation_id, id);
--
-- Name: agent_tasks agent_tasks_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_tasks
    ADD CONSTRAINT agent_tasks_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.analysis_jobs(id);
--
-- Name: agent_tasks agent_tasks_job_tenant_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_tasks
    ADD CONSTRAINT agent_tasks_job_tenant_fkey FOREIGN KEY (organisation_id, job_id) REFERENCES public.analysis_jobs(organisation_id, id);
--
-- Name: agent_tasks agent_tasks_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.agent_tasks
    ADD CONSTRAINT agent_tasks_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: analysis_jobs analysis_jobs_dataset_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT analysis_jobs_dataset_version_id_fkey FOREIGN KEY (dataset_version_id) REFERENCES public.dataset_versions(id);
--
-- Name: analysis_jobs analysis_jobs_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT analysis_jobs_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: analysis_jobs analysis_jobs_requested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT analysis_jobs_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.profiles(id);
--
-- Name: analysis_jobs analysis_jobs_version_tenant_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT analysis_jobs_version_tenant_fkey FOREIGN KEY (organisation_id, dataset_version_id) REFERENCES public.dataset_versions(organisation_id, id);
--
-- Name: analysis_jobs analysis_jobs_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT analysis_jobs_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);
--
-- Name: analysis_jobs analysis_jobs_workspace_tenant_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_jobs
    ADD CONSTRAINT analysis_jobs_workspace_tenant_fkey FOREIGN KEY (organisation_id, workspace_id) REFERENCES public.workspaces(organisation_id, id);
--
-- Name: analysis_results analysis_results_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_results
    ADD CONSTRAINT analysis_results_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.analysis_jobs(id);
--
-- Name: analysis_results analysis_results_job_tenant_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_results
    ADD CONSTRAINT analysis_results_job_tenant_fkey FOREIGN KEY (organisation_id, job_id) REFERENCES public.analysis_jobs(organisation_id, id);
--
-- Name: analysis_results analysis_results_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.analysis_results
    ADD CONSTRAINT analysis_results_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: artifacts artifacts_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.analysis_jobs(id);
--
-- Name: artifacts artifacts_job_tenant_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_job_tenant_fkey FOREIGN KEY (organisation_id, job_id) REFERENCES public.analysis_jobs(organisation_id, id);
--
-- Name: artifacts artifacts_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.artifacts
    ADD CONSTRAINT artifacts_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: audit_logs audit_logs_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: dataset_columns dataset_columns_dataset_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_columns
    ADD CONSTRAINT dataset_columns_dataset_version_id_fkey FOREIGN KEY (dataset_version_id) REFERENCES public.dataset_versions(id);
--
-- Name: dataset_columns dataset_columns_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_columns
    ADD CONSTRAINT dataset_columns_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: dataset_columns dataset_columns_version_tenant_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_columns
    ADD CONSTRAINT dataset_columns_version_tenant_fkey FOREIGN KEY (organisation_id, dataset_version_id) REFERENCES public.dataset_versions(organisation_id, id);
--
-- Name: dataset_versions dataset_versions_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT dataset_versions_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.profiles(id);
--
-- Name: dataset_versions dataset_versions_dataset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT dataset_versions_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES public.datasets(id);
--
-- Name: dataset_versions dataset_versions_dataset_tenant_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT dataset_versions_dataset_tenant_fkey FOREIGN KEY (organisation_id, dataset_id) REFERENCES public.datasets(organisation_id, id);
--
-- Name: dataset_versions dataset_versions_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.dataset_versions
    ADD CONSTRAINT dataset_versions_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: datasets datasets_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.profiles(id);
--
-- Name: datasets datasets_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: datasets datasets_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspaces(id);
--
-- Name: datasets datasets_workspace_tenant_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.datasets
    ADD CONSTRAINT datasets_workspace_tenant_fkey FOREIGN KEY (organisation_id, workspace_id) REFERENCES public.workspaces(organisation_id, id);
--
-- Name: organisation_memberships organisation_memberships_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.organisation_memberships
    ADD CONSTRAINT organisation_memberships_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: organisation_memberships organisation_memberships_role_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.organisation_memberships
    ADD CONSTRAINT organisation_memberships_role_fkey FOREIGN KEY (role) REFERENCES public.roles(name);
--
-- Name: organisation_memberships organisation_memberships_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.organisation_memberships
    ADD CONSTRAINT organisation_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id);
--
-- Name: profiles profiles_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.profiles
    ADD CONSTRAINT profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id);
--
-- Name: stored_file_chunks stored_file_chunks_key_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.stored_file_chunks
    ADD CONSTRAINT stored_file_chunks_key_fkey FOREIGN KEY (key) REFERENCES public.stored_files(key) ON DELETE CASCADE;
--
-- Name: usage_records usage_records_job_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.analysis_jobs(id);
--
-- Name: usage_records usage_records_job_tenant_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_job_tenant_fkey FOREIGN KEY (organisation_id, job_id) REFERENCES public.analysis_jobs(organisation_id, id);
--
-- Name: usage_records usage_records_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: workspaces workspaces_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.profiles(id);
--
-- Name: workspaces workspaces_organisation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--
ALTER TABLE ONLY public.workspaces
    ADD CONSTRAINT workspaces_organisation_id_fkey FOREIGN KEY (organisation_id) REFERENCES public.organisations(id);
--
-- Name: agent_runs; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.agent_runs ENABLE ROW LEVEL SECURITY;
--
-- Name: agent_runs agent_runs_member_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY agent_runs_member_select ON public.agent_runs FOR SELECT TO tatmaq_app_user USING (public.is_org_member(organisation_id));
--
-- Name: agent_tasks; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.agent_tasks ENABLE ROW LEVEL SECURITY;
--
-- Name: agent_tasks agent_tasks_member_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY agent_tasks_member_select ON public.agent_tasks FOR SELECT TO tatmaq_app_user USING (public.is_org_member(organisation_id));
--
-- Name: analysis_jobs; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.analysis_jobs ENABLE ROW LEVEL SECURITY;
--
-- Name: analysis_jobs analysis_jobs_member_insert; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY analysis_jobs_member_insert ON public.analysis_jobs FOR INSERT TO tatmaq_app_user WITH CHECK (public.has_org_role(organisation_id, ARRAY['owner'::text, 'admin'::text, 'analyst'::text]));
--
-- Name: analysis_jobs analysis_jobs_member_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY analysis_jobs_member_select ON public.analysis_jobs FOR SELECT TO tatmaq_app_user USING (public.is_org_member(organisation_id));
--
-- Name: analysis_jobs analysis_jobs_member_update; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY analysis_jobs_member_update ON public.analysis_jobs FOR UPDATE TO tatmaq_app_user USING (public.has_org_role(organisation_id, ARRAY['owner'::text, 'admin'::text, 'analyst'::text])) WITH CHECK (public.has_org_role(organisation_id, ARRAY['owner'::text, 'admin'::text, 'analyst'::text]));
--
-- Name: analysis_results; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.analysis_results ENABLE ROW LEVEL SECURITY;
--
-- Name: analysis_results analysis_results_member_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY analysis_results_member_select ON public.analysis_results FOR SELECT TO tatmaq_app_user USING (public.is_org_member(organisation_id));
--
-- Name: artifacts; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.artifacts ENABLE ROW LEVEL SECURITY;
--
-- Name: artifacts artifacts_member_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY artifacts_member_select ON public.artifacts FOR SELECT TO tatmaq_app_user USING (public.is_org_member(organisation_id));
--
-- Name: audit_logs; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;
--
-- Name: audit_logs audit_logs_admin_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY audit_logs_admin_select ON public.audit_logs FOR SELECT TO tatmaq_app_user USING (public.has_org_role(organisation_id, ARRAY['owner'::text, 'admin'::text]));
--
-- Name: audit_logs audit_logs_member_insert; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY audit_logs_member_insert ON public.audit_logs FOR INSERT TO tatmaq_app_user WITH CHECK ((public.is_org_member(organisation_id) AND (actor_id = public.app_user_id())));
--
-- Name: dataset_columns; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.dataset_columns ENABLE ROW LEVEL SECURITY;
--
-- Name: dataset_columns dataset_columns_member_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY dataset_columns_member_select ON public.dataset_columns FOR SELECT TO tatmaq_app_user USING (public.is_org_member(organisation_id));
--
-- Name: dataset_versions; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.dataset_versions ENABLE ROW LEVEL SECURITY;
--
-- Name: dataset_versions dataset_versions_member_insert; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY dataset_versions_member_insert ON public.dataset_versions FOR INSERT TO tatmaq_app_user WITH CHECK (public.has_org_role(organisation_id, ARRAY['owner'::text, 'admin'::text, 'analyst'::text]));
--
-- Name: dataset_versions dataset_versions_member_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY dataset_versions_member_select ON public.dataset_versions FOR SELECT TO tatmaq_app_user USING (public.is_org_member(organisation_id));
--
-- Name: datasets; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.datasets ENABLE ROW LEVEL SECURITY;
--
-- Name: datasets datasets_member_access; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY datasets_member_access ON public.datasets FOR SELECT TO tatmaq_app_user USING (public.is_org_member(organisation_id));
--
-- Name: datasets datasets_member_insert; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY datasets_member_insert ON public.datasets FOR INSERT TO tatmaq_app_user WITH CHECK (public.has_org_role(organisation_id, ARRAY['owner'::text, 'admin'::text, 'analyst'::text]));
--
-- Name: datasets datasets_member_update; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY datasets_member_update ON public.datasets FOR UPDATE TO tatmaq_app_user USING (public.has_org_role(organisation_id, ARRAY['owner'::text, 'admin'::text, 'analyst'::text])) WITH CHECK (public.has_org_role(organisation_id, ARRAY['owner'::text, 'admin'::text, 'analyst'::text]));
--
-- Name: organisation_memberships memberships_visible_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY memberships_visible_select ON public.organisation_memberships FOR SELECT TO tatmaq_app_user USING (((user_id = public.app_user_id()) OR public.is_org_member(organisation_id)));
--
-- Name: organisation_memberships; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.organisation_memberships ENABLE ROW LEVEL SECURITY;
--
-- Name: organisations; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.organisations ENABLE ROW LEVEL SECURITY;
--
-- Name: organisations organisations_member_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY organisations_member_select ON public.organisations FOR SELECT TO tatmaq_app_user USING (public.is_org_member(id));
--
-- Name: profiles; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
--
-- Name: profiles profiles_self_insert; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY profiles_self_insert ON public.profiles FOR INSERT TO tatmaq_app_user WITH CHECK ((id = public.app_user_id()));
--
-- Name: profiles profiles_self_update; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY profiles_self_update ON public.profiles FOR UPDATE TO tatmaq_app_user USING ((id = public.app_user_id())) WITH CHECK ((id = public.app_user_id()));
--
-- Name: profiles profiles_visible_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY profiles_visible_select ON public.profiles FOR SELECT TO tatmaq_app_user USING (((id = public.app_user_id()) OR public.shares_org_with(id)));
--
-- Name: roles; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.roles ENABLE ROW LEVEL SECURITY;
--
-- Name: roles roles_read; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY roles_read ON public.roles FOR SELECT TO tatmaq_app_user USING (true);
--
-- Name: stored_file_chunks; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.stored_file_chunks ENABLE ROW LEVEL SECURITY;
--
-- Name: stored_files; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.stored_files ENABLE ROW LEVEL SECURITY;
--
-- Name: usage_records; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.usage_records ENABLE ROW LEVEL SECURITY;
--
-- Name: usage_records usage_records_member_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY usage_records_member_select ON public.usage_records FOR SELECT TO tatmaq_app_user USING (public.is_org_member(organisation_id));
--
-- Name: workspaces; Type: ROW SECURITY; Schema: public; Owner: -
--
ALTER TABLE public.workspaces ENABLE ROW LEVEL SECURITY;
--
-- Name: workspaces workspaces_admin_insert; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY workspaces_admin_insert ON public.workspaces FOR INSERT TO tatmaq_app_user WITH CHECK (public.has_org_role(organisation_id, ARRAY['owner'::text, 'admin'::text]));
--
-- Name: workspaces workspaces_admin_update; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY workspaces_admin_update ON public.workspaces FOR UPDATE TO tatmaq_app_user USING (public.has_org_role(organisation_id, ARRAY['owner'::text, 'admin'::text])) WITH CHECK (public.has_org_role(organisation_id, ARRAY['owner'::text, 'admin'::text]));
--
-- Name: workspaces workspaces_member_select; Type: POLICY; Schema: public; Owner: -
--
CREATE POLICY workspaces_member_select ON public.workspaces FOR SELECT TO tatmaq_app_user USING (public.is_org_member(organisation_id));
--
-- PostgreSQL database dump complete
--
