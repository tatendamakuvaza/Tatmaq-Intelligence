# The agent bridge

Two different things are called "connecting to Arena", and this page separates them.

| Direction | What it is | What it needs |
| --- | --- | --- |
| **App → Arena models** | The AI assistant and the agents' planning/narrative call Arena's model API (`https://api.arena.ai/v1`). | An Arena API key (`AI_PROVIDER=arena`). Optional: everything works without it. |
| **Agent → app** (this bridge) | An external AI assistant — an Arena Agent Mode session, or any MCP client — signs in to your installation and works with your real datasets and verified results. | A bridge account with the `agent` role. No Arena key needed. |

**What the bridge is not.** Arena's Agent Mode (the chat with a sandbox, file tools and connectors)
has no public API that an outside application can call. This bridge is the other way round: it lets
an agent reach *your* system. The model your app calls and the agent you chat with are separate
sessions; what carries knowledge between them is this repository and the organisation's learning
profile.

## What the bridge account may do

The `agent` role is deliberately narrow:

| Allowed | Not allowed |
| --- | --- |
| Read every dataset, analysis, finding and report in its organisation | Read or write anything in another organisation (Row Level Security) |
| Upload datasets, run and cancel analyses | Manage the organisation, its members or its workspaces |
| Download reports | Change any figure: the API only returns verified results |
| Record lessons in the learning profile (`learning:write`) | Rewrite the business context, glossary, preferences or report style (owners and admins only) |

Every action is written to the audit log with the agent's own user id, exactly like a person's.
Access is cut off immediately by suspending the membership (`revoke`), and passwords can be rotated
without touching anything else.

## Set it up (three steps)

**1. Deploy the current code.** The bridge needs the `agent` role and the `learning:write`
permission, which `scripts/migrate.py` installs. On Render this happens automatically at container
start; elsewhere run `python scripts/migrate.py` first.

**2. Create the account**, pointed at the same database the API uses:

```bash
# Windows cmd: set DATABASE_URL first, or put it in .env
set DATABASE_URL=postgresql://user:password@host:5432/dbname
python scripts/agent_account.py create --organisation your-organisation-slug
```

It prints the password once, the organisation id, and a ready-to-paste prompt for a new Arena chat.
Use `--api-url` if your API is not `https://tatmaq-api.onrender.com`.

**3. Paste that prompt into a new Arena chat.** The agent clones this repository, reads this page,
and uses `scripts/tatmaq_agent.py` against your live API.

To withdraw access:

```bash
python scripts/agent_account.py revoke --email arena-agent@tatmaq.local
python scripts/agent_account.py list
python scripts/agent_account.py rotate --email arena-agent@tatmaq.local
```

## Using it from an Arena session

The sandbox has Python and network access, so no installation is needed:

```bash
git clone https://github.com/tatendamakuvaza/Tatmaq-Intelligence.git
cd Tatmaq-Intelligence
export TATMAQ_API_URL=https://tatmaq-api.onrender.com
export TATMAQ_EMAIL=arena-agent@tatmaq.local
export TATMAQ_PASSWORD=...              # or TATMAQ_TOKEN for an 8-hour token
export TATMAQ_ORGANISATION_ID=...

python scripts/tatmaq_agent.py whoami
python scripts/tatmaq_agent.py datasets
python scripts/tatmaq_agent.py analyse <dataset_version_id> "Which products are most profitable?" --wait
python scripts/tatmaq_agent.py results <job_id>
python scripts/tatmaq_agent.py lesson "Always compare branches." --source "board review"
```

| Command | Returns |
| --- | --- |
| `whoami` | Account, organisation, role, permissions, server config, workspaces |
| `datasets` | Datasets with latest version ids, rows, columns, status |
| `profile <dataset_id>` | Column dictionary, data-quality findings, cleaning log |
| `analyse <version_id> "<prompt>" [--wait]` | A job id, or the finished job |
| `job <job_id>` | Agent-by-agent progress and warnings |
| `results <job_id>` | Verified findings, figures, charts, tables, report ids |
| `reports` | Report files that exist |
| `learning` / `lesson "<text>"` | Read the learning profile / record a lesson |
| `feedback <job_id> helpful\|not_helpful ["<lesson>"]` | Rate an analysis |

Add `--json` to any command for machine-readable output. Prefer a short-lived token
(`TATMAQ_TOKEN`, from `POST /v1/auth/login`) over the password when you paste credentials into a
chat; it expires after eight hours.

## Using it from an MCP client

`scripts/tatmaq_mcp.py` speaks MCP over stdio and exposes the same operations as ten tools
(`tatmaq_whoami`, `tatmaq_datasets`, `tatmaq_dataset_profile`, `tatmaq_analyse`, `tatmaq_job`,
`tatmaq_results`, `tatmaq_reports`, `tatmaq_learning`, `tatmaq_add_lesson`, `tatmaq_feedback`).

```json
{
  "mcpServers": {
    "tatmaq": {
      "command": "python",
      "args": ["C:/Users/Admin/Tatmaq-Intelligence/scripts/tatmaq_mcp.py"],
      "env": {
        "TATMAQ_API_URL": "https://tatmaq-api.onrender.com",
        "TATMAQ_EMAIL": "arena-agent@tatmaq.local",
        "TATMAQ_PASSWORD": "...",
        "TATMAQ_ORGANISATION_ID": "..."
      }
    }
  }
}
```

Arena's Agent Mode does not accept a custom MCP connector, so there use the CLI above.

## Turning on Arena models inside the app

This is the other direction, and it is independent of the bridge.

1. Arena's API is an **invite-only developer preview**. Request access at
   [platform.arena.ai](https://platform.arena.ai) and join the waitlist if you are not in yet.
2. When you have access, create a key under **Dashboard → Keys** (it is shown once) and enable the
   model you want for that key in your workspace.
3. In the Render service → **Environment**, set:

   | Key | Value |
   | --- | --- |
   | `AI_PROVIDER` | `arena` |
   | `AI_API_KEY` | the key (never commit it, never paste it into a chat) |
   | `AI_MODEL` | a model enabled for the key, e.g. `coding-router-preview` |
   | `AI_BASE_URL` | leave empty — it defaults to `https://api.arena.ai/v1` |

4. Redeploy. `/v1/config` then reports `ai_enabled: true`, the Agents page shows the connected
   model, and the AI assistant answers alongside the TATMAQ agents.

If a request fails with `403 organization_client_restricted`, your Arena workspace only allows
approved clients; ask your workspace admin to allow API access for the key.

**Meanwhile:** with `AI_PROVIDER=none` the planner uses built-in rules, reports use templates, and
the AI assistant still shows the verified TATMAQ answer. Any other OpenAI-compatible provider works
too (`AI_PROVIDER=openai_compatible` with its `AI_BASE_URL` and `AI_MODEL`), so you are not blocked
on Arena's preview.
