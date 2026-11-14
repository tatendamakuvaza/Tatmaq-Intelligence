# Architecture

## Shape

A **modular monolith with a separate worker**, as the specification recommends. One Python codebase
(`apps/api`) runs as two kinds of process:

| Process | Command | Does |
| --- | --- | --- |
| API | `uvicorn app.main:app` | Authenticates, authorises, validates, queues jobs. Never loads a dataset. |
| Worker | `python -m app.workers.worker` | Claims jobs and supervises one short-lived child process per job. |
| Job runner | started by the worker | Runs one job's LangGraph workflow, then exits. |

The web app (`apps/web`) talks only to the API. PostgreSQL holds the data and is also the job queue.
Files live behind one storage interface: local disk in development, and in production either
PostgreSQL itself (for hosts whose disk is wiped on restart) or a private Supabase bucket.

## Request path

1. The browser sends `Authorization: Bearer <token>` and `X-Organisation-Id`.
2. `security/auth.py` verifies the token; `security/tenancy.py` confirms the caller is an active
   member of that organisation and loads their permissions into a `TenantContext`.
3. Service functions take the `TenantContext`, never a bare organisation id from the request.
4. Every statement runs in a session bound to the restricted database role, so Row Level Security
   filters it as well (see `docs/security`).

## A job

`POST /v1/analysis-jobs` inserts a row with status `queued` and returns at once. A worker claims it
with `SELECT ... FOR UPDATE SKIP LOCKED`, receives a random lock token, and starts a runner.

```
queued -> validating_dataset -> planning -> executing_agents -> quality_verification -> generating_report
       -> completed | partially_completed | failed | cancelled
```

| Concern | Mechanism | Code |
| --- | --- | --- |
| No job runs twice | `SKIP LOCKED` claim | `workers/queue.py` |
| A presumed-dead worker cannot write | every write names the lock token (fencing) | `workers/queue.py` |
| A crashed worker loses nothing | heartbeats; stale jobs are requeued up to `max_attempts` | `queue.recover_stale` |
| A resumed job does not redo work | each task's result is stored with a fingerprint of its input and reused | `agents/orchestration/tasks.py` |
| A duplicate request starts nothing new | `Idempotency-Key` header, unique per organisation | `services/jobs.py` |
| Usage is never counted twice | one usage row per (metric, source) | `services/usage.py` |
| One job cannot take the server down | own process, address-space cap, wall-clock limit, row and size limits | `workers/limits.py`, `workers/worker.py` |
| Cancellation | queued: immediate. Running: the worker stops the process. | `services/jobs.py`, `workers/worker.py` |

Retries and resumption are implemented per task against PostgreSQL rather than with a LangGraph
checkpointer: the database is already the durable record, and it keeps one source of truth.

## The calculation boundary

```
request ──planner (rules, or an AI model)──> AnalysisSpec ──deterministic code──> results ──reconciliation──> report
```

`analytics/spec.py` defines the specification: eight operation types over named columns, validated
with Pydantic and then against the dataset's actual columns. `packages/analytics-core` does the
arithmetic and imports nothing from the application. `analytics/verification.py` reconciles the
results. Only then does the Report agent see them.

## Measured capacity (development machine, 2 CPU, 2 GB)

| File | Import and clean | Analyse (sales + profitability) | Peak memory of the job |
| --- | --- | --- | --- |
| 3,750 rows, 0.2 MB xlsx | 1.4 s | 0.5 s | not measured (small) |
| 300,000 rows, 17 MB csv | 10 s | 8 s | 0.5 GB |
| 850,000 rows, 47 MB csv | 22 s | 16 s | 0.86 GB |

Plan on roughly 1 GB of memory per million rows. On a 1 GB container keep datasets under about
300,000 rows by lowering `MAX_ANALYSIS_ROWS`, and set `JOB_MAX_MEMORY_MB` below the container's
memory (the cap counts address space, which runs about 600 MB above memory in use).

### On a small server (512 MB, a tenth of a CPU core)

Measured in November 2026 with the API image built from `infrastructure/docker/api.Dockerfile`,
started by `start-all.sh` with built-in sign-in and database storage, in a container limited to
512 MB and 0.1 CPU: the size of a typical free container.

| | Result |
| --- | --- |
| Start to first answer (migrations, API, worker) | 35 to 47 s |
| Idle memory, API and worker together | about 160 MB |
| 3,750 rows (the sample workbook) | import 35 to 59 s, analysis 34 to 48 s; figures match the benchmark |
| 50,000 rows, nine columns, 3.7 MB csv | import 45 s, analysis 42 s; memory at the ceiling, nothing killed |
| 100,000 rows, nine columns, 7.5 MB csv | completed (import 72 s, analysis 59 s) with no memory to spare |
| 50,000 rows, thirty columns, 26 MB csv | too large: the job was stopped and reported as such; the API kept running |

For a server of that size set `MAX_UPLOAD_MB=5` and `MAX_ANALYSIS_ROWS=50000`, and leave
`JOB_MAX_MEMORY_MB` at its default. Lowering that cap towards the memory really in use was tried
(800 to 900) and behaved erratically: the same cap gave a clean refusal, a repeated internal error,
or a job that ran until the ten-minute limit, depending on the file. Limiting what may be uploaded
is the dependable control; the cap is a last resort for larger machines.

What happens at the limit was tested, not assumed. With the cap at 1024 MB a 300,000-row import was
refused; on a machine that ran out of memory outright, the operating system killed the job's
process. In both cases the worker, API and database kept running and the job ended as failed with
"This dataset is too large to process within the memory available."
