# Contracts

JSON Schema for the data structures shared across TATMAQ Intelligence.

| Folder | Contents |
| --- | --- |
| `agent_schemas/` | What every agent receives (`agent_task`) and must return (`agent_result`), and the `analysis_spec` that separates understanding a request from calculating its answer |
| `api_schemas/` | Request and response bodies of the REST API |
| `event_schemas/` | What a client observes while a job runs |

These files are **generated**. The Pydantic models in `apps/api` are the source of truth:

```bash
python scripts/export_contracts.py          # regenerate after changing a model
python scripts/export_contracts.py --check  # CI fails if they are out of date
```
