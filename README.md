# TATMAQ Intelligence

**Your AI analytics department.** A customer uploads an Excel or CSV file, asks a question in plain
language, watches five agents work on it, and downloads a verified report as PDF, Excel and HTML.

This repository is the MVP 1.0 starter described in the Technical Implementation Specification v1.0:
a working application, not a set of placeholders.

| | |
| --- | --- |
| Web app | Next.js 16 (`apps/web`) |
| API, agents, worker | Python 3.13, FastAPI, LangGraph (`apps/api`) |
| Calculation engine | pandas, NumPy, SciPy, statsmodels, exact `Decimal` money (`packages/analytics-core`) |
| Database and queue | PostgreSQL 17 with Row Level Security (`database/`) |
| Sign-in | Built-in email-and-password accounts, or Supabase Auth |
| File storage | The database itself, a Supabase bucket, or local disk |
| AI model | Optional and provider-independent. Everything runs without one. |

## Run it locally

**With Docker** (PostgreSQL, API, worker and web app in one command):

```bash
docker compose up --build
# open http://localhost:3000, create an account, then click "Use sample data"
```

**Without Docker** (you need Python 3.12+, Node.js 22+ and a PostgreSQL 15+ server):

```bash
cp .env.example .env                       # then set DATABASE_URL to your PostgreSQL server

python -m venv .venv && source .venv/bin/activate
pip install -r apps/api/requirements.lock -r apps/api/requirements-dev.lock
pip install --no-deps -e packages/analytics-core -e apps/api

python scripts/migrate.py                  # creates the schema, security policies and roles

# three terminals:
cd apps/api && uvicorn app.main:app --reload --port 8000     # API   (docs at http://localhost:8000/docs)
cd apps/api && python -m app.workers.worker                  # worker
cd apps/web && npm ci && npm run dev                         # web   (http://localhost:3000)
```

Check a running installation end to end at any time:

```bash
python scripts/smoke_test.py               # signs up, uploads the sample, analyses it, downloads the PDF
```

## How it works

```
 Browser ──> Next.js web app ──/api──> FastAPI ──> PostgreSQL  <── worker (one child process per job)
                                          │        (data, queue, RLS)        │
                                          └──────> file storage <────────────┘

 An analysis job:

   Chief Intelligence ─> Data Acquisition ─> Data Cleaning ─> Statistical Analysis ─> Quality Verification ─> Report Generation
   plans the work        verifies the file   checks the data  calculates            reconciles the results   PDF, Excel, HTML
        ^                                         │               ^                        │
        └──── re-plan if the data cannot ─────────┘               └──── recompute once ────┘
              support part of the plan                                  if a check fails
```

The rule everything else follows from: **an AI model may help understand a request and word a
summary, but it never produces a number.**

1. A request becomes an *analysis specification*: a closed list of operations over named columns.
   There is no way to express code, SQL or a figure in it, and it is validated against the dataset's
   real columns. With no AI model configured, built-in rules write it.
2. Deterministic code executes the specification. Money is added in exact decimal arithmetic.
3. The results are reconciled (parts add up to totals, profit equals sales less cost, totals agree
   with a second independent calculation). If a check fails, nothing is reported.
4. Reports are written from approved findings only. If an AI model drafts the summary, any draft
   containing a figure that is not in the verified results is discarded.

Every finding carries its evidence: the formula, the columns, the rows used and left out, and the
SHA-256 fingerprint of the file it came from.

## What is in the repository

```
apps/web                 the web app: sign-in, dashboard, analyst, datasets, reports, agents, settings
apps/api/app
  api/ schemas/ services/  REST endpoints (versioned under /v1) and business logic
  agents/                  the five agents, their tool permissions, and the LangGraph workflows
  analytics/               the analysis specification, number formatting, quality verification
  security/ storage/ llm/  sign-in, tenancy, signed links; file storage (disk, database, Supabase); AI providers
  workers/                 the PostgreSQL job queue, the supervising worker, the per-job runner
packages/analytics-core  the calculation engine: cleaning, statistics, financial maths, reconciliation
packages/contracts       JSON Schema of every agent and API contract (generated)
database                 SQL migrations, Row Level Security policies, seeds, schema snapshot
infrastructure           Dockerfiles, deployment guide, monitoring notes
scripts                  migrate, accounts (create, reset password), smoke test, benchmark data, contract export
docs                     architecture, agents, API, database, security
```

## Tests

```bash
docker compose up -d db                    # or point TEST_DATABASE_URL at any PostgreSQL server
pytest packages/analytics-core apps/api/tests
cd apps/web && npm run lint && npm run typecheck && npm run build
```

265 tests run against a real PostgreSQL database (Row Level Security and the queue cannot be tested
honestly against a stand-in). They are organised around the specification's acceptance criteria:

| Acceptance criterion (spec Part J) | Where it is tested |
| --- | --- |
| Customer A cannot access Customer B's data | `test_tenant_isolation.py`: through the API and directly in the database |
| A failed upload does not create a usable dataset | `test_uploads.py` |
| A duplicate request creates no duplicate charges or reports | `test_jobs.py` |
| A failed agent can be retried safely; an interrupted worker loses nothing | `test_queue_worker.py` |
| The source of every finding is recorded | `test_benchmark.py` |
| Monetary calculations reconcile with independent results | `test_benchmark.py`, `analytics-core/tests` |
| Users cannot download files outside their permissions | `test_tenant_isolation.py` |
| Large files cannot exhaust the server | `test_uploads.py`, `test_queue_worker.py` |
| Reports are generated, retrievable and consistent with findings | `test_benchmark.py`, `test_agents.py` |

**The benchmark dataset.** `apps/api/tests/benchmark/` holds a year of sales for a fictional
wholesaler, deliberately messy (duplicates, gaps, three date formats, numbers typed as text, a TOTAL
line). Its answers in `expected.json` are computed by the generator in integer cents, sharing no code
with the engine. The full pipeline must reproduce them to the cent, from both the Excel and the CSV
version. Run that test after every change to an agent.

## Configuration

All server settings are environment variables, documented in [`.env.example`](.env.example); the web
app's public settings are in [`apps/web/.env.example`](apps/web/.env.example). Unsafe combinations
(development sign-in in production, a missing signing key, wildcard CORS) stop the server at start-up.

To connect an AI model, set `AI_PROVIDER`, `AI_API_KEY` and `AI_MODEL`. `openai_compatible` works
with any provider that offers an OpenAI-style API (set `AI_BASE_URL`); `anthropic` uses Anthropic's
API.

## Deployment

See [`infrastructure/deployment/README.md`](infrastructure/deployment/README.md). It describes two
arrangements: a free one (Netlify for the web app, Render for the API and worker, Aiven for
PostgreSQL) in which the application keeps its own accounts and files, and the specification's
original one with Supabase. [`render.yaml`](render.yaml) and [`netlify.toml`](netlify.toml) hold the
settings for the free arrangement.

## Status

**Verified in development** (by the test-suite, by a browser-driven run of the whole flow on desktop
and phone-sized screens, and by `scripts/smoke_test.py`): everything in the table above, uploads up to
the 50 MB limit, and a 850,000-row file (47 MB) imported in 22 s and analysed in 16 s using 0.86 GB.

**Verified as it would be deployed for free** (13 November 2026): the API image, built from its
Dockerfile and started with `start-all.sh`, with built-in sign-in and files in the database, in a
container limited to 512 MB and a tenth of a CPU core, against a PostgreSQL server restricted like a
free managed one. It survived having its disk wiped. The details and the measured limits are in the
deployment guide and `docs/architecture/overview.md`.

**Written but not yet run against the real service** (do these checks before relying on them):

- Netlify, Render and Aiven themselves: the settings in `netlify.toml` and `render.yaml` follow their
  documentation but have not been applied on live accounts.
- `docker compose up` and the web app's Dockerfile. The API's Dockerfile was built and run with
  Podman, not Docker.
- Supabase Auth and Supabase Storage: tested against local stand-ins and scripted HTTP, not a live
  project. The migrations were run as a non-superuser shaped like Supabase's `postgres` role.
- The OpenAI-compatible and Anthropic clients: tested against scripted HTTP, not live APIs.
- The GitHub Actions workflow on GitHub itself (its steps pass when run by hand).

**Not built yet:** confirmation and "forgot password" emails for the built-in sign-in (passwords are
reset with `scripts/accounts.py`), inviting colleagues to an organisation, correcting a column's recognised role by
hand, choosing a worksheet other than the largest, group comparisons and hypothesis tests beyond
trend/correlation/regression, clustering, subscriptions and payments, live progress over
Server-Sent Events (the app polls), `.xls`/PDF/JSON/SQL sources, agents 06 to 12.

**Decisions to confirm:** the `LICENSE` file is a placeholder; reporting currency defaults to USD and
ambiguous dates are read day-first (both per organisation, see `.env.example`).
