#!/usr/bin/env python3
"""Talk to a TATMAQ Intelligence installation as an external agent. Standard library only.

    export TATMAQ_API_URL=https://tatmaq-api.onrender.com
    export TATMAQ_EMAIL=arena-agent@example.com
    export TATMAQ_PASSWORD=...                 # or TATMAQ_TOKEN for an 8-hour token
    export TATMAQ_ORGANISATION_ID=...          # optional when the account belongs to one

    python scripts/tatmaq_agent.py whoami
    python scripts/tatmaq_agent.py datasets
    python scripts/tatmaq_agent.py profile <dataset_id>
    python scripts/tatmaq_agent.py analyse <dataset_version_id> "Which products are most profitable?" --wait
    python scripts/tatmaq_agent.py results <job_id>
    python scripts/tatmaq_agent.py reports
    python scripts/tatmaq_agent.py learning
    python scripts/tatmaq_agent.py lesson "Always compare branches."
    python scripts/tatmaq_agent.py feedback <job_id> helpful "Break results down by branch."

Every command prints JSON with --json, which is what another program (or an AI agent)
should read. Nothing here calculates anything: the figures come from the server's
verified results, exactly as the web app shows them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

DEFAULT_API_URL = "http://127.0.0.1:8000"
TERMINAL = {"completed", "partially_completed", "failed", "cancelled"}


class AgentError(RuntimeError):
    """The API refused the request or could not be reached."""


# (method, url, headers, body bytes) -> (status, parsed JSON or None)
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, Any]]


def http_transport(method: str, url: str, headers: dict[str, str], body: bytes | None) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw) if raw else None
        except ValueError:
            return error.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise AgentError(f"Could not reach {url}: {error}") from error


class TatmaqClient:
    """A thin, authenticated client for the /v1 API."""

    def __init__(
        self,
        base_url: str = DEFAULT_API_URL,
        *,
        token: str | None = None,
        email: str | None = None,
        password: str | None = None,
        organisation_id: str | None = None,
        transport: Transport = http_transport,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.root = self.base_url if self.base_url.endswith("/v1") else f"{self.base_url}/v1"
        self.token, self.email, self.password = token, email, password
        self.organisation_id = organisation_id
        self._transport = transport

    # ------------------------------------------------------------------ plumbing

    def _call(self, method: str, path: str, body: Any = None, *, authenticated: bool = True, retry: bool = True) -> Any:
        headers = {"Accept": "application/json"}
        if authenticated:
            if not self.token:
                self.login()
            headers["Authorization"] = f"Bearer {self.token}"
            if self.organisation_id:
                headers["X-Organisation-Id"] = self.organisation_id
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        status, parsed = self._transport(method, f"{self.root}{path}", headers, data)
        if status == 401 and authenticated and retry and self.email and self.password:
            # The 8-hour token expired: sign in once more and repeat the request.
            self.token = None
            return self._call(method, path, body, authenticated=True, retry=False)
        if status >= 400:
            message = (parsed or {}).get("error", {}).get("message") if isinstance(parsed, dict) else None
            raise AgentError(message or f"The API returned {status} for {method} {path}.")
        return parsed

    def login(self) -> dict[str, Any]:
        if not (self.email and self.password):
            raise AgentError("No credentials. Set TATMAQ_EMAIL and TATMAQ_PASSWORD, or TATMAQ_TOKEN.")
        session = self._call(
            "POST", "/auth/login", {"email": self.email, "password": self.password}, authenticated=False
        )
        self.token = session["access_token"]
        return session

    def organisations(self) -> list[dict[str, Any]]:
        return self._call("GET", "/organisations")

    def ensure_organisation(self) -> dict[str, Any]:
        """Choose the organisation to act in: the one given, or the only one the account belongs to."""
        organisations = self.organisations()
        if not organisations:
            raise AgentError("This account belongs to no organisation.")
        if self.organisation_id:
            for organisation in organisations:
                if organisation["id"] == self.organisation_id:
                    return organisation
            raise AgentError("This account is not a member of the organisation in TATMAQ_ORGANISATION_ID.")
        if len(organisations) > 1:
            raise AgentError("This account belongs to several organisations. Set TATMAQ_ORGANISATION_ID.")
        self.organisation_id = organisations[0]["id"]
        return organisations[0]

    # ------------------------------------------------------------------ tools

    def whoami(self) -> dict[str, Any]:
        organisation = self.ensure_organisation()
        return {
            "api": self.base_url,
            "account": self.email or "(token)",
            "organisation": {"id": organisation["id"], "name": organisation["name"], "role": organisation["role"]},
            "permissions": organisation["permissions"],
            "config": self._call("GET", "/config", authenticated=False),
            "workspaces": self._call("GET", "/workspaces"),
        }

    def datasets(self) -> list[dict[str, Any]]:
        self.ensure_organisation()
        return self._call("GET", "/datasets")

    def dataset_profile(self, dataset_id: str) -> dict[str, Any]:
        self.ensure_organisation()
        return self._call("GET", f"/datasets/{dataset_id}/profile")

    def analyse(
        self,
        dataset_version_id: str,
        prompt: str,
        *,
        analysis_type: str = "automatic",
        workspace_id: str | None = None,
        wait: bool = False,
        timeout_seconds: int = 900,
    ) -> dict[str, Any]:
        self.ensure_organisation()
        if workspace_id is None:
            workspaces = self._call("GET", "/workspaces")
            if not workspaces:
                raise AgentError("This organisation has no workspace.")
            workspace_id = workspaces[0]["id"]
        accepted = self._call(
            "POST", "/analysis-jobs",
            {"workspace_id": workspace_id, "dataset_version_id": dataset_version_id,
             "prompt": prompt, "analysis_type": analysis_type},
        )  # fmt: skip
        job_id = accepted["job_id"]
        if not wait:
            return {"job_id": job_id, "status": accepted["status"]}
        deadline = time.monotonic() + timeout_seconds
        while True:
            job = self._call("GET", f"/analysis-jobs/{job_id}")
            if job["status"] in TERMINAL:
                return job
            if time.monotonic() > deadline:
                return job
            time.sleep(2)

    def job(self, job_id: str) -> dict[str, Any]:
        self.ensure_organisation()
        return self._call("GET", f"/analysis-jobs/{job_id}/agents")

    def results(self, job_id: str) -> dict[str, Any]:
        self.ensure_organisation()
        return self._call("GET", f"/analysis-jobs/{job_id}/results")

    def reports(self) -> list[dict[str, Any]]:
        self.ensure_organisation()
        return self._call("GET", "/reports")

    def learning(self) -> dict[str, Any]:
        self.ensure_organisation()
        return self._call("GET", "/organisations/learning-profile")

    def add_lesson(self, lesson: str, source: str | None = None) -> dict[str, Any]:
        self.ensure_organisation()
        body: dict[str, Any] = {"lesson": lesson}
        if source:
            body["source"] = source
        return self._call("POST", "/organisations/learning-profile/lessons", body)

    def feedback(self, job_id: str, rating: str, lesson: str | None = None) -> dict[str, Any]:
        self.ensure_organisation()
        return self._call("POST", f"/analysis-jobs/{job_id}/feedback", {"rating": rating, "lesson": lesson})


def client_from_env() -> TatmaqClient:
    return TatmaqClient(
        os.environ.get("TATMAQ_API_URL", DEFAULT_API_URL),
        token=os.environ.get("TATMAQ_TOKEN") or None,
        email=os.environ.get("TATMAQ_EMAIL") or None,
        password=os.environ.get("TATMAQ_PASSWORD") or None,
        organisation_id=os.environ.get("TATMAQ_ORGANISATION_ID") or None,
    )


# --------------------------------------------------------------------------- human output


def _print_datasets(datasets: list[dict[str, Any]]) -> None:
    for dataset in datasets:
        version = dataset.get("latest_version") or {}
        print(f"{dataset['id']}  {dataset['status']:<10} {dataset['name']}")
        if version:
            print(
                f"    version {version.get('version_number')} id={version.get('id')} "
                f"rows={version.get('row_count')} columns={version.get('column_count')}"
            )


def _print_results(results: dict[str, Any]) -> None:
    summary = results.get("summary") or {}
    print(summary.get("headline") or results["job"]["prompt"])
    for point in summary.get("executive_summary", []):
        print(f"  - {point}")
    for step in summary.get("next_steps", []):
        print(f"  next: {step}")
    verification = summary.get("verification") or {}
    checks = verification.get("checks", [])
    print(f"  checks passed: {sum(1 for c in checks if c['passed'])}/{len(checks)}")
    for finding in results.get("findings", []):
        if finding.get("approved"):
            print(f"  [{finding.get('evidence_ref')}] {finding.get('statement')}")
    for report in results.get("reports", []):
        print(f"  report {report['format']}: {report['id']} {report.get('filename')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--json", action="store_true", help="print the raw JSON response")
    # --json is accepted on either side of the command, which is easier to type and to script.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name: str, help_text: str):
        return commands.add_parser(name, help=help_text, parents=[common])

    command("whoami", "account, organisation, permissions and server configuration")
    command("datasets", "datasets and their latest versions")
    command("profile", "column dictionary and data quality").add_argument("dataset_id")
    analyse = command("analyse", "run an analysis")
    analyse.add_argument("dataset_version_id")
    analyse.add_argument("prompt")
    analyse.add_argument("--type", default="automatic", dest="analysis_type")
    analyse.add_argument("--workspace-id")
    analyse.add_argument("--wait", action="store_true", help="poll until the analysis finishes")
    command("job", "agent-by-agent progress").add_argument("job_id")
    command("results", "verified findings, figures and reports").add_argument("job_id")
    command("reports", "report files")
    command("learning", "the organisation's learning profile")
    lesson = command("lesson", "record a lesson for the agents")
    lesson.add_argument("text")
    lesson.add_argument("--source")
    feedback = command("feedback", "rate an analysis")
    feedback.add_argument("job_id")
    feedback.add_argument("rating", choices=["helpful", "not_helpful"])
    feedback.add_argument("lesson", nargs="?")
    arguments = parser.parse_args(argv)

    client = client_from_env()
    try:
        if arguments.command == "whoami":
            data = client.whoami()
        elif arguments.command == "datasets":
            data = client.datasets()
        elif arguments.command == "profile":
            data = client.dataset_profile(arguments.dataset_id)
        elif arguments.command == "analyse":
            data = client.analyse(
                arguments.dataset_version_id,
                arguments.prompt,
                analysis_type=arguments.analysis_type,
                workspace_id=arguments.workspace_id,
                wait=arguments.wait,
            )
        elif arguments.command == "job":
            data = client.job(arguments.job_id)
        elif arguments.command == "results":
            data = client.results(arguments.job_id)
        elif arguments.command == "reports":
            data = client.reports()
        elif arguments.command == "learning":
            data = client.learning()
        elif arguments.command == "lesson":
            data = client.add_lesson(arguments.text, arguments.source)
        else:
            data = client.feedback(arguments.job_id, arguments.rating, arguments.lesson)
    except AgentError as error:
        print(f"Failed: {error}", file=sys.stderr)
        return 1

    if arguments.json or arguments.command in {"whoami", "profile", "job", "learning", "lesson", "feedback"}:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif arguments.command == "datasets":
        _print_datasets(data)
    elif arguments.command == "results":
        _print_results(data)
    elif arguments.command == "reports":
        for report in data:
            print(f"{report['id']}  {report['format']:<5} {report.get('filename')}  {report.get('dataset_name')}")
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
