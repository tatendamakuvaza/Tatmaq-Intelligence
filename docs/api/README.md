# API

Base path `/v1`. Interactive documentation is served at `/docs` outside production.

Every request except those marked *public* needs `Authorization: Bearer <access token>`. Requests
that act inside an organisation also need `X-Organisation-Id`. Errors always have the shape
`{"error": {"code": "...", "message": "..."}}`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/config` | *Public.* What the web app needs before sign-in |
| POST | `/auth/profile` | Create or update the caller's profile (safe to repeat) |
| GET, POST | `/organisations` | List the caller's organisations; create one (with a first workspace) |
| GET | `/organisations/members` | People in the organisation |
| GET, POST | `/workspaces` | List, create |
| GET | `/datasets` | List (optional `workspace_id`) |
| POST | `/datasets/upload-url` | Upload step 1: register the dataset, get a one-off upload link |
| POST | `/datasets/{id}/complete` | Upload step 3: confirm the file arrived, start importing (safe to repeat) |
| GET | `/datasets/{id}` | Details and versions |
| GET | `/datasets/{id}/profile` | Column dictionary, data quality findings, cleaning log |
| POST | `/analysis-jobs` | Submit an analysis (send an `Idempotency-Key` header) |
| GET | `/analysis-jobs` | Recent analyses |
| GET | `/analysis-jobs/{id}` | Status |
| GET | `/analysis-jobs/{id}/agents` | Each agent's progress, summary and warnings |
| GET | `/analysis-jobs/{id}/results` | Verified findings with evidence, figures, charts, tables, reports |
| POST | `/analysis-jobs/{id}/cancel` | Cancel a queued or running analysis |
| GET | `/reports` | List report files |
| GET | `/reports/{id}/download` | A short-lived download link (recorded in the audit log) |
| GET | `/usage` | This month's usage and the plan's limits |
| GET | `/agents` | The agent team and recent agent activity |

Built-in sign-in only (`AUTH_MODE=builtin` or `dev`):

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/auth/register` | *Public.* Create an account and sign in. `403 signups_closed` when `ALLOW_SIGNUPS=false` |
| POST | `/auth/login` | *Public.* Sign in. `429 too_many_attempts` while an account is locked after five wrong passwords |
| POST | `/auth/password` | Change the caller's own password (`403` wrong current password, `400` unacceptable new one) |

Files the API stores itself (`STORAGE_BACKEND=local` or `database`): `PUT /uploads/{token}`,
`GET /files/{token}`. The signed token in the address is the permission; no sign-in header is sent.
Outside `/v1`: `GET /healthz` (process is up), `GET /readyz` (database reachable).

## Uploading a file

```
POST /v1/datasets/upload-url   {"workspace_id": "...", "filename": "sales.xlsx", "size_bytes": 166764}
  -> {"dataset_id": "...", "upload": {"method": "PUT", "url": "...", "headers": {...}}}
PUT  <upload.url>              the file bytes, with upload.headers
POST /v1/datasets/{dataset_id}/complete
  -> {"dataset_version_id": "...", "job_id": "...", "status": "processing"}
```

`upload.url` is relative (served by this API) with local or database storage, and an absolute Supabase URL with
Supabase Storage. Poll `GET /datasets/{id}` until `status` is `ready` or `failed`.

## Submitting an analysis

```
POST /v1/analysis-jobs         Idempotency-Key: 6f1c...   (any unique string per click)
  {"workspace_id": "...", "dataset_version_id": "...", "prompt": "Which products are most profitable?",
   "analysis_type": "automatic"}
  -> 202 {"job_id": "...", "status": "queued", "message": "Your analysis has been submitted."}
```

Repeating the request with the same key returns the same job with status 200. `analysis_type` is one
of `automatic`, `sales`, `profitability`, `statistical`, `data_quality`. Poll
`GET /analysis-jobs/{id}/agents` once a second until `job.is_finished`.
