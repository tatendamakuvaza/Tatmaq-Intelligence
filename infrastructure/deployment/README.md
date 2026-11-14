# Deployment

The application has three parts, and each can live on a different host:

| Part | What it is | Needs |
| --- | --- | --- |
| Web app | the pages people see (`apps/web`, Next.js) | a Next.js host |
| API and worker | one container that answers requests and runs analyses | a container host with at least 512 MB |
| Database | PostgreSQL 15 or newer | any PostgreSQL provider |

Two arrangements are described here. **A** costs nothing and depends on no service beyond a plain
PostgreSQL database. **B** is the specification's original arrangement, using Supabase.

> Neither arrangement has been run on the live services named here: no accounts were available
> where this was built. What *was* run is listed under "What has been tested" for arrangement A.
> Expect to adjust a detail the first time through, and finish with the check in section 4.

## A. Free: Netlify, Render and Aiven

The application keeps its own accounts (`AUTH_MODE=builtin`) and its own files
(`STORAGE_BACKEND=database`), so the database is the only thing that has to last. Do the three
steps in this order: each needs something from the one before.

### 1. Database: Aiven

1. Sign up at aiven.io (no card is asked for) and create a service: **PostgreSQL**, plan **Free**.
2. When the service shows **Running**, open it and copy the **Service URI**. It looks like
   `postgres://avnadmin:...@...aivencloud.com:12345/defaultdb?sslmode=require`. Treat it as a
   password.

Nothing else is needed here: the API creates its tables itself the first time it starts.

### 2. API and worker: Render

1. Sign up at render.com with your GitHub account and choose **New > Blueprint**.
2. Pick this repository. Render reads [`render.yaml`](../../render.yaml) and asks for two values:
   - `DATABASE_URL`: the Service URI from step 1.
   - `CORS_ALLOWED_ORIGINS`: the address your web app will have, for example
     `https://tatmaq.netlify.app`. No slash at the end. You can correct it after step 3.
3. Apply. The first build takes several minutes. When the service is **Live**, note its address
   (for example `https://tatmaq-api.onrender.com`) and open `<that address>/healthz`: it should
   answer `{"status":"ok",...}`.

`render.yaml` sets `plan: free`. If Render shows a paid plan or asks for a card, stop and check
that line before continuing.

### 3. Web app: Netlify

1. Sign up at netlify.com with your GitHub account and choose **Add new project > Import an
   existing project**, then pick this repository. [`netlify.toml`](../../netlify.toml) supplies the
   build settings.
2. Before deploying, add one environment variable:
   `NEXT_PUBLIC_API_BASE_URL` = the Render address from step 2 (no slash at the end).
3. Deploy. Then compare the site's address with what you gave Render as `CORS_ALLOWED_ORIGINS`.
   If they differ, correct the value in Render (**Environment**), which restarts the service.

A private repository must belong to your personal GitHub account: Netlify's free plan does not
build private repositories owned by a GitHub organisation.

### 4. Check it

Open the Netlify address, create an account, click **Use sample data** and run an analysis. Or,
from a computer with the project set up:

```bash
python scripts/smoke_test.py --base-url https://tatmaq-api.onrender.com
```

### 5. Afterwards

- **Close sign-ups** once your own account exists, if strangers should not be able to register:
  add `ALLOW_SIGNUPS=false` to the service's environment in Render.
- **Accounts and forgotten passwords.** The built-in sign-in sends no email. From a computer with
  the project set up, with `DATABASE_URL` set to the Service URI:

  ```bash
  python scripts/accounts.py list
  python scripts/accounts.py create someone@example.com          # prints a temporary password
  python scripts/accounts.py reset-password someone@example.com  # also clears a lock
  ```
- **Never change `APP_SECRET_KEY`** unless you mean to: it signs every session and every file link,
  so changing it signs everyone out.

### What the free plans mean in practice

| | Behaviour | Source |
| --- | --- | --- |
| Render | The service is stopped after 15 minutes without traffic; the next request waits while it starts again. Allow one to two minutes: Render's own start, then about 40 s for this application. The sign-in page says so while it waits. | Render's documentation; measured |
| Render | 512 MB of memory. With the limits in `render.yaml` (5 MB, 50,000 rows) a file is analysed in one to two minutes. Larger files are refused with a clear message. | measured, see `docs/architecture/overview.md` |
| Render | "Do not use them for production applications" is Render's own advice for free instances. A paid instance does not sleep. | Render's documentation |
| Aiven | 1 GB for everything, uploaded files and reports included; 20 connections; a service left unused may be powered off after a warning, and powered on again from the console. | Aiven's documentation |
| Netlify | 300 credits a month; each production deploy costs 15, so at most 20 a month; when credits run out the site pauses until the next month. Deploy previews are free. | Netlify's pricing page |

These were read from the providers' pages in November 2026. Free plans change: check before relying
on them.

### What has been tested

On 13 November 2026, with nothing but this repository:

- The API image was built from `infrastructure/docker/api.Dockerfile` and started with
  `start-all.sh` and the settings in `render.yaml`, in a container limited to 512 MB and a tenth of
  a CPU core, against a PostgreSQL server set up like Aiven's free plan: an administrator that is
  not a superuser, encrypted connections only, 20 connections. Sign-up, upload, import, analysis and
  report download completed with figures matching the benchmark. At most 5 connections were open.
- With the web app on one address and the API on another, a real browser went through sign-up,
  analysis, all three report downloads, changing a password, the lock after five wrong passwords,
  and the "server is starting" notice.
- The API and worker were stopped, everything on their disk was deleted, and they were started
  again: the account, the dataset and the earlier reports were all still there, and a new analysis
  ran on the old dataset.

Not tested: Netlify's build of the web app, Render's handling of the Blueprint, and a real Aiven
database.

## B. With Supabase: Supabase, any container host, any Next.js host

Supabase provides the database, the sign-in and the file storage.

### 1. Supabase

1. Create a project. From **Connect**, copy the PostgreSQL connection string (the pooler URL is fine;
   the API does not use server-side prepared statements).
2. Apply the schema from your machine:
   ```bash
   DATABASE_URL='postgresql://postgres.<ref>:<password>@<host>:5432/postgres' python scripts/migrate.py
   ```
   Because a Supabase database already has an `auth` schema, this project's own is not installed.
3. **Authentication:** enable email sign-in; set the Site URL to your web app's address. Under JWT
   signing keys, use asymmetric keys.
4. **API keys:** create a *publishable* key (for the web app) and a *secret* key (for the API and
   worker only). Supabase is retiring the older `anon` and `service_role` keys.
5. **Storage:** create a **private** bucket named `tatmaq-private` with a file-size limit of 50 MB.
6. Optional: switch off the Data API. The app does not use it, and the policies already grant its
   roles nothing.

### 2. API and worker (any container host)

Build `infrastructure/docker/api.Dockerfile` from the repository root. Run it with the command
`/srv/infrastructure/docker/start-all.sh`, which applies migrations, then runs the API and one worker
and exits if either stops. Give it at least 1 GB of memory for files beyond the small-server limits
(see `docs/architecture/overview.md`).

```
APP_ENV=production
APP_SECRET_KEY=<48 random characters>
DATABASE_URL=<Supabase connection string>
AUTH_MODE=supabase
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
SUPABASE_SECRET_KEY=sb_secret_...
STORAGE_BACKEND=supabase
OBJECT_STORAGE_BUCKET=tatmaq-private
CORS_ALLOWED_ORIGINS=https://app.yourdomain.com
```

As usage grows, run the worker as its own service (`python -m app.workers.worker`), or several: the
queue hands each job to exactly one.

### 3. Web app (Netlify or Vercel)

Import the repository with the root (base) directory `apps/web`, Node.js 22, and:

```
NEXT_PUBLIC_API_BASE_URL=https://api.yourdomain.com
NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

### 4. Verify

```bash
python scripts/smoke_test.py --base-url https://api.yourdomain.com --token <access token of a test user>
```

## In both arrangements

Set `NEXT_PUBLIC_API_BASE_URL`. Without it the browser uses the web app's `/api` proxy, which is
meant for development: hosting platforms cap proxied request sizes, and every call would count
against the web host's allowance.

Work through the checklist at the end of `docs/security/README.md` before real customers use it.

## Costs

Arrangement A costs nothing while it stays inside the free plans above. The specification's target
of roughly USD 10 to 30 a month buys what the free plans lack: a server that does not sleep and has
more memory, and a database with room to grow. It is a planning figure, not a quotation: check
current prices. Do not promise customers uptime on free plans.
