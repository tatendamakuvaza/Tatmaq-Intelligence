# Security

## Tenant isolation: two independent layers

**Layer 1, the API.** Each request resolves a `TenantContext` (verified user, organisation,
permissions). Every query filters by that organisation. An id from a URL or request body never
chooses the tenant; another organisation's resource answers `404`, the same as one that does not
exist.

**Layer 2, the database.** The API does not query as its login role. `core/database.py` starts every
transaction of an end-user request with

```sql
SET LOCAL ROLE tatmaq_app_user;
SELECT set_config('request.jwt.claims', '{"sub": "<user id>"}', true);
```

`tatmaq_app_user` can see a row only through the Row Level Security policies in
`database/policies/001_row_level_security.sql`, which test membership with `is_org_member()` (the
function from the specification, extended so a suspended organisation loses access too). A query
that forgets its organisation filter returns nothing from other tenants. With no user set, the role
sees nothing. The role is re-applied at the start of *every* transaction, including after a commit
in the middle of a request.

That role also cannot delete anything, cannot write results, artifacts, agent history or usage, and
can update only named columns (it can request a cancellation; it cannot rewrite a job's results).
The audit log is append-only.

**The worker** uses the privileged connection, because it must write those tables. It therefore
re-verifies each job's organisation itself (`JobContext.load_dataset`), and every tool it gives an
agent refuses a storage path outside that organisation's prefix.

**Supabase's browser-facing roles** (`anon`, `authenticated`) are granted nothing on these tables,
and the policies file revokes whatever a project's defaults granted. The web app uses Supabase only
to sign in; it never reads tables directly. You can additionally switch off the Data API in the
Supabase dashboard.

This differs from the specification's example in one respect: policies are written for the API's own
role rather than for `authenticated`, and end users get no direct INSERT path. Writes go through the
API, where allowances, limits and validation apply.

## Authentication

`AUTH_MODE` chooses who keeps the accounts.

- **Built-in (`AUTH_MODE=builtin`).** The application keeps its own email-and-password accounts in
  its database. Passwords are stored only as salted scrypt hashes. Five wrong passwords in a row
  lock the account for fifteen minutes, whether they come through sign-in or through the
  change-password form, and attempts on one account are checked one at a time. A session is a signed
  token that lasts eight hours; its signing key is derived from `APP_SECRET_KEY`, so whoever holds
  that secret can sign in as anyone. `ALLOW_SIGNUPS=false` closes sign-up; the administrator then
  creates accounts and resets passwords with `scripts/accounts.py`.

  What it does not do, by design or not yet: it sends no email, so an address is not confirmed and
  there is no "forgot password" link; changing a password does not end sessions already open (they
  expire within eight hours); and attempts are limited per account, not per network address.
- **Supabase Auth (`AUTH_MODE=supabase`).** Tokens signed with the project's asymmetric keys
  (ES256/RS256) are verified locally against the published JWKS, checking signature, issuer,
  audience, expiry and that the token is a signed-in (not anonymous, not service) user. Projects
  still on the legacy shared secret are verified by asking the Auth server, as Supabase recommends.
- **Development (`AUTH_MODE=dev`).** The built-in accounts with a fixed, published signing secret,
  so a laptop needs no configuration. The server refuses to start with it when `APP_ENV=production`.

Built-in accounts are only ever written to this project's own `auth` schema: the code checks that
schema's marker first, so passwords can never land in a real Supabase `auth.users` table.

## Files

- Storage keys are built from UUIDs: `org/{organisation}/datasets/{dataset}/v{n}/original.xlsx`. A
  customer's filename is kept for display and never becomes a path.
- **Originals are write-once.** A second upload to the same key is refused by storage; a new upload
  makes a new version. The file's SHA-256 is recorded at import and re-checked at the start of every
  analysis; a mismatch stops the analysis.
- Upload and download links are signed, short-lived, and bound to one object and one purpose.
- With `STORAGE_BACKEND=database` the files are rows in `stored_files` and `stored_file_chunks`. The
  role that end-user requests run as has no privileges on those tables at all, so a file is still
  reachable only through a signed link or by the worker.
- Size is enforced on bytes received, not on what the client declares. `.xlsx` files are checked as
  archives (including for decompression bombs) before being opened.

## Analysis execution (specification 8.1)

| Safeguard | How |
| --- | --- |
| No arbitrary code from prompts | A prompt can only become an `AnalysisSpec`: a closed vocabulary validated against real columns |
| No operating-system commands or free database queries | No agent has such a tool |
| Read-only datasets | Analysis agents hold a reader only; derived tables are written by the import step |
| Tool permissions per agent | `agents/base/permissions.py`, enforced by `Toolbox` |
| CPU, memory, time limits | One process per job with an address-space cap; wall-clock limit enforced by the worker |
| Isolated temporary directory | Each job gets its own folder, removed afterwards |
| Complete execution logging | `agent_tasks`, `agent_runs`, `audit_logs` |
| No network access for analytical workers | Enforced in code (analysis agents have no network tool), **not** at the operating-system level. For defence in depth, restrict the worker's outbound traffic to the database, storage and the AI provider at your host. |

## AI model

- It receives the request text and the column dictionary (names, types, counts). It is never sent
  rows. `test_agents.py` asserts this.
- Request text and column names are treated as data. Whatever the model returns must validate as a
  specification and fit the dataset, or the built-in planner is used.
- A drafted summary is discarded if it contains a figure that is not in the verified results, or an
  allegation of dishonesty.

## Reports

Customer text is escaped in HTML and PDF, and written as text (never as a formula) in Excel. The
HTML report contains no scripts and loads nothing from the network; the app shows it in a sandboxed
frame.

## Before going live

- [ ] `APP_ENV=production`, `AUTH_MODE=builtin` or `supabase`, a random `APP_SECRET_KEY`, explicit `CORS_ALLOWED_ORIGINS`
- [ ] Built-in sign-in: `APP_SECRET_KEY` is known only to the host; decide whether sign-ups stay open (`ALLOW_SIGNUPS`)
- [ ] Supabase: the secret key (`sb_secret_...`) exists only in the API and worker environment, never in the web app
- [ ] Supabase: asymmetric JWT signing keys enabled; the storage bucket is private, with a file-size limit equal to `MAX_UPLOAD_MB`
- [ ] `python scripts/smoke_test.py` passes against the deployment
- [ ] As a second user in a second organisation, confirm you cannot see the first one's data
- [ ] Database backups switched on; a restore has been tried once
- [ ] Rate limiting by network address in front of the API (not built in; the built-in sign-in limits attempts per account only)
