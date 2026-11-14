#!/usr/bin/env python3
"""Export the platform's data contracts as JSON Schema into packages/contracts/.

    python scripts/export_contracts.py            # rewrite the schema files
    python scripts/export_contracts.py --check    # fail if the files are out of date (used in CI)

The Pydantic models in apps/api are the single source of truth. The JSON Schema files
are generated from them so that other languages (the web app today, a mobile app or a
partner integration later) can validate against exactly what the API enforces.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from app.agents.base import contracts as agent
from app.analytics.spec import AnalysisSpec
from app.schemas import accounts, datasets, jobs

OUTPUT = Path(__file__).resolve().parent.parent / "packages" / "contracts"

CONTRACTS: dict[str, dict[str, type[BaseModel]]] = {
    "agent_schemas": {
        "agent_task": agent.AgentTask,
        "agent_result": agent.AgentResult,
        "analysis_spec": AnalysisSpec,
    },
    "api_schemas": {
        "job_request": jobs.JobRequest,
        "job_accepted": jobs.JobAccepted,
        "job": jobs.JobOut,
        "job_results": jobs.JobResults,
        "agent_activity": jobs.AgentActivity,
        "report": jobs.ReportOut,
        "download_link": jobs.DownloadLink,
        "upload_request": datasets.UploadRequest,
        "upload_response": datasets.UploadResponse,
        "dataset": datasets.DatasetDetail,
        "dataset_profile": datasets.DatasetProfile,
        "organisation": accounts.OrganisationOut,
        "workspace": accounts.WorkspaceOut,
    },
    # What a client observes as a job progresses. Today it polls GET /analysis-jobs/{id}/agents;
    # the same shape would be pushed over Server-Sent Events.
    "event_schemas": {
        "job_progress": jobs.AgentActivity,
    },
}


def render(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for folder, models in CONTRACTS.items():
        for name, model in models.items():
            path = OUTPUT / folder / f"{name}.schema.json"
            content = render(model)
            if check:
                if not path.exists() or path.read_text(encoding="utf-8") != content:
                    stale.append(str(path.relative_to(OUTPUT.parent.parent)))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
    if stale:
        print("Out of date (run scripts/export_contracts.py):\n  " + "\n  ".join(stale), file=sys.stderr)
        return 1
    print(f"{sum(len(m) for m in CONTRACTS.values())} contract schemas {'are up to date' if check else 'written'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
