# Monitoring

What exists today, and what to watch.

- **Health:** `GET /healthz` (process up) and `GET /readyz` (database reachable). Point your host's
  health check at `/healthz` and an uptime monitor at `/readyz`.
- **Logs:** the API, worker and job runner write one JSON object per line to standard output, with
  `job_id` on every job event. Any log collector can ingest them.
- **History in the database:** `agent_runs` (every attempt, duration, AI tokens, error),
  `audit_logs`, `usage_records`.

Alert on:

| Signal | Query or source | Meaning |
| --- | --- | --- |
| Queue backing up | `SELECT count(*) FROM analysis_jobs WHERE status = 'queued' AND created_at < now() - interval '5 minutes'` | No worker running, or too few |
| Failure rate | `SELECT count(*) FILTER (WHERE status = 'failed') * 1.0 / count(*) FROM analysis_jobs WHERE created_at > now() - interval '1 day'` | A bad release or a provider outage |
| Recovered jobs | log message `recovered a job whose worker stopped responding` | Workers are crashing or being killed |
| Memory kills | log message `job process was killed` | Datasets too large for the container: add memory or lower `MAX_ANALYSIS_ROWS` |
| Verification failures | job error containing `did not pass verification` | A calculation bug: investigate before anything else |

Not set up yet: metrics export, tracing, error reporting, dashboards.
