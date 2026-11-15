# Database

PostgreSQL 15 or newer (developed and tested on 17). The schema is owned by SQL files, applied by
`python scripts/migrate.py`, which works the same against local PostgreSQL and a Supabase project.

| Folder | Applied | Contents |
| --- | --- | --- |
| `database/migrations/` | once each, in order, recorded with a checksum | `0001` the specification's 15 tables; `0002` constraints, tenant-aware keys, queue columns, indexes; `0003` the two tables that hold files when `STORAGE_BACKEND=database`; `0004` `organisations.learning_profile` (JSONB guidance for the agents) |
| `database/policies/` | on every run (idempotent) | the restricted role, helper functions, Row Level Security policies, privileges |
| `database/seeds/` | on every run (idempotent) | the five system roles and their permissions (`owner`, `admin`, `analyst`, `viewer`, `agent`) |
| `database/local/` | once each, but only when the database has no `auth` schema or has this project's own (never on Supabase) | `000` a stand-in for Supabase's `auth.users` and `auth.uid()`; `001` what the built-in sign-in adds to it (the lock after repeated wrong passwords) |
| `database/schema.sql` | never (generated, for reading) | the resulting schema in one file |

An applied migration is immutable: the runner refuses to continue if its checksum changes. To change
the schema, add `0005_...sql`. To change a policy or a role's permissions, edit the file and re-run.

Beyond the 15 tables below there are three kinds of supporting table: `schema_migrations` (the
runner's own record), `stored_files` and `stored_file_chunks` (file contents in pieces of at most
1 MB, used only with `STORAGE_BACKEND=database`; the end-user role has no privileges on them), and
`auth.users` (accounts: Supabase's own table on Supabase, this project's on plain PostgreSQL).

## The 15 tables

```
organisations ─┬─ organisation_memberships ── profiles (= auth.users)      roles
               ├─ workspaces ─┬─ datasets ── dataset_versions ── dataset_columns
               │              └─ analysis_jobs ─┬─ agent_tasks ── agent_runs
               │                                ├─ analysis_results
               │                                └─ artifacts
               ├─ audit_logs
               └─ usage_records
```

Every tenant-owned table carries `organisation_id`.

## What was added to the specification's schema, and why

- **Tenant-aware foreign keys.** Parents have `UNIQUE (organisation_id, id)` and children reference
  `(organisation_id, parent_id)` together. The database itself refuses a row in organisation A that
  points at a parent in organisation B, even from privileged code.
- **Status constraints** on every status column, and a rule that a dataset version cannot be `ready`
  without its cleaned data, profile and fingerprint.
- **Queue columns** on `analysis_jobs`: `job_type`, `attempts`, `max_attempts`, `locked_by`,
  `lock_token`, `heartbeat_at`, `cancel_requested_at`, with partial indexes for the queue and for
  in-flight jobs.
- **Idempotency.** `UNIQUE (organisation_id, idempotency_key)` on jobs (from the specification),
  `UNIQUE (job_id, artifact_type)` on artifacts, `UNIQUE (organisation_id, metric, source_key)` on
  usage records: a retried job cannot duplicate reports or usage.
- **`dataset_columns.organisation_id`**, so the table can be protected like the others.
- **Organisation locale**: `default_currency`, `timezone`, `date_order`.
- **`organisations.learning_profile`** (migration `0004`): a JSONB object with the agents' guidance
  (business context, glossary, preferences, report style, lessons). A column-level `UPDATE` grant and
  an owner/admin `UPDATE` policy let only owners and admins change it; everyone in the organisation
  may read it. It is never used to calculate figures.
- `pgcrypto` is not required: `gen_random_uuid()` is built into PostgreSQL 13+.
- `analysis_results.confidence` is left empty for calculated figures. They are exact for the rows
  used; how many rows were used is recorded in the evidence instead.

## Useful queries

```sql
-- queue depth and in-flight work
SELECT status, count(*) FROM analysis_jobs WHERE status NOT IN ('completed','failed','cancelled','partially_completed') GROUP BY 1;

-- what each agent did for one job
SELECT t.sequence, t.agent_key, t.status, r.attempt, r.duration_ms, r.error_message
FROM agent_tasks t LEFT JOIN agent_runs r ON r.task_id = t.id WHERE t.job_id = '<job id>' ORDER BY 1, 4;

-- who did what
SELECT created_at, actor_id, action, resource_type, details FROM audit_logs WHERE organisation_id = '<id>' ORDER BY 1 DESC;
```
