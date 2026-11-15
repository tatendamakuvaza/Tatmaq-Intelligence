"""The agent bridge: the least-privilege ``agent`` role, the setup script, the CLI client and the MCP server.

The role is checked through the API and against the database. The client and the MCP
server are checked against a scripted transport, so no live installation is needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(REPO_ROOT / "scripts")]

import agent_account
import tatmaq_agent
import tatmaq_mcp

from conftest import add_member, new_account, run_queued_jobs

PROMPT = "Analyse my sales and identify my most profitable products."


def bridge_member(client, owner):
    member = new_account(client, "Bridge assistant")
    add_member(owner.organisation_id, member.user_id, "agent")
    member.organisation_id, member.workspace_id = owner.organisation_id, owner.workspace_id
    return member


# --------------------------------------------------------------------------- the agent role


def test_agent_role_can_analyse_and_teach_but_not_administer(client, account, small_csv):
    version = account.upload(small_csv)["dataset_version_id"]
    agent = bridge_member(client, account)

    permissions = agent.get("/organisations").json()[0]["permissions"]
    assert "learning:write" in permissions and "analysis:run" in permissions
    assert "organisation:manage" not in permissions and "members:manage" not in permissions

    assert agent.get("/datasets").status_code == 200
    submitted = agent.post("/analysis-jobs", json={
        "workspace_id": account.workspace_id, "dataset_version_id": version, "prompt": PROMPT})  # fmt: skip
    assert submitted.status_code == 202, submitted.text
    run_queued_jobs()
    job_id = submitted.json()["job_id"]
    results = agent.get(f"/analysis-jobs/{job_id}/results")
    assert results.status_code == 200 and results.json()["summary"]["verification"]["passed"]

    # It may record a lesson, but not rewrite the profile, create workspaces or manage people.
    assert (
        agent.post("/organisations/learning-profile/lessons", json={"lesson": "Compare branches."}).status_code == 200
    )
    assert "Compare branches." in account.get("/organisations/learning-profile").json()["lessons"][0]
    assert agent.client.put("/v1/organisations/learning-profile", json={"business_context": "rewritten"},
                            headers=agent.headers).status_code == 403  # fmt: skip
    assert agent.post("/workspaces", json={"name": "Extra"}).status_code == 403
    assert agent.post(
        f"/analysis-jobs/{job_id}/feedback", json={"rating": "helpful", "lesson": "Keep it short."}
    ).json() == {
        "recorded": True,
        "lesson_saved": True,
    }


def test_agent_role_stays_inside_its_organisation(client, make_account, small_csv):
    owner, other = make_account("Bridge owner"), make_account("Other company")
    agent = bridge_member(client, owner)
    job = other.analyse(other.upload(small_csv)["dataset_version_id"], PROMPT)
    assert agent.get(f"/analysis-jobs/{job['id']}/results").status_code == 404
    assert agent.get("/datasets").json() == []
    assert agent.post("/organisations/learning-profile/lessons", json={"lesson": "x"}).status_code == 200
    assert other.get("/organisations/learning-profile").json()["lessons"] == []


def test_the_database_refuses_the_agent_role_any_other_column(client, account, database_url):
    agent = bridge_member(client, account)
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            connection.execute("SET LOCAL ROLE tatmaq_app_user")
            connection.execute(
                "SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": agent.user_id}),)
            )
            allowed = connection.execute(
                "UPDATE organisations SET learning_profile = %s WHERE id = %s",
                (json.dumps({"lessons": ["from the database"]}), account.organisation_id),
            )
            assert allowed.rowcount == 1
        with connection.transaction():
            connection.execute("SET LOCAL ROLE tatmaq_app_user")
            connection.execute(
                "SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": agent.user_id}),)
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "UPDATE organisations SET name = 'renamed' WHERE id = %s", (account.organisation_id,)
                )


# --------------------------------------------------------------------------- the setup script


def test_setup_script_creates_a_working_least_privilege_account(client, account, database_url):
    slug = account.get("/organisations").json()[0]["slug"]
    email = f"bridge-{uuid4().hex[:10]}@example.com"
    password, organisation_id, name = agent_account.create(database_url, email, slug, "Arena Agent")
    assert organisation_id == account.organisation_id and name

    signed_in = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert signed_in.status_code == 200, signed_in.text
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}", "X-Organisation-Id": organisation_id}
    organisations = client.get("/v1/organisations", headers=headers).json()
    assert [o["role"] for o in organisations] == ["agent"]
    assert (
        client.post(
            "/v1/organisations/learning-profile/lessons", json={"lesson": "Bridge works."}, headers=headers
        ).status_code
        == 200
    )
    assert client.post("/v1/workspaces", json={"name": "Nope"}, headers=headers).status_code == 403

    assert agent_account.list_agents(database_url)[0][0] == email
    assert agent_account.revoke(database_url, email) == 1
    # The token is still valid, but the suspended membership means the organisation no longer exists for it.
    assert client.get("/v1/datasets", headers=headers).status_code == 404
    assert agent_account.rotate(database_url, email)


# --------------------------------------------------------------------------- the CLI client


class FakeApi:
    """A scripted stand-in for the HTTP API: (method, url, headers, body) -> (status, json)."""

    def __init__(self, *, expire_first_token: bool = False):
        self.calls: list[tuple[str, str]] = []
        self.expire_first_token = expire_first_token
        self.logins = 0

    def __call__(self, method, url, headers, body):
        path = url.split("/v1", 1)[1]
        self.calls.append((method, path))
        payload = json.loads(body) if body else None
        if path == "/auth/login":
            self.logins += 1
            assert payload == {"email": "agent@example.com", "password": "secret"}
            return 200, {"access_token": f"token-{self.logins}", "expires_in": 28800}
        if path == "/config":
            return 200, {"ai_enabled": False, "ai_provider": "none"}
        if headers.get("Authorization") == "Bearer token-1" and self.expire_first_token:
            self.expire_first_token = False
            return 401, {"error": {"code": "token_expired", "message": "Your session has expired."}}
        assert headers.get("Authorization", "").startswith("Bearer token-")
        # The organisation header appears once the client has chosen an organisation;
        # listing them is how it chooses, so that one call is unscoped.
        if path != "/organisations":
            assert headers.get("X-Organisation-Id") == "org-1"
        if path == "/organisations":
            return 200, [
                {"id": "org-1", "name": "Mopane", "role": "agent", "permissions": ["analysis:run", "learning:write"]}
            ]
        if path == "/workspaces":
            return 200, [{"id": "ws-1", "name": "Main"}]
        if path == "/datasets":
            return 200, [
                {
                    "id": "ds-1",
                    "name": "Sales",
                    "status": "ready",
                    "latest_version": {"id": "v-1", "version_number": 1, "row_count": 6, "column_count": 7},
                }
            ]
        if path == "/analysis-jobs" and method == "POST":
            assert payload["workspace_id"] == "ws-1" and payload["dataset_version_id"] == "v-1"
            return 202, {"job_id": "job-1", "status": "queued"}
        if path == "/analysis-jobs/job-1":
            return 200, {"id": "job-1", "status": "completed", "is_finished": True}
        if path == "/analysis-jobs/job-1/results":
            return 200, {
                "job": {"id": "job-1", "prompt": PROMPT},
                "summary": {
                    "headline": "Sales were USD 36.50.",
                    "executive_summary": ["Sales were USD 36.50."],
                    "next_steps": [],
                    "verification": {"passed": True, "checks": [{"passed": True}]},
                },
                "findings": [{"approved": True, "statement": "Sugar 2kg sold best.", "evidence_ref": "E1"}],
                "reports": [{"id": "r-1", "format": "pdf", "filename": "report.pdf"}],
            }
        if path == "/organisations/learning-profile/lessons" and method == "POST":
            assert payload["lesson"] == "Compare branches."
            return 200, {"lessons": ["Compare branches."]}
        if path == "/organisations/learning-profile":
            return 200, {"lessons": [], "report_style": "executive"}
        if path == "/reports":
            return 200, [{"id": "r-1", "format": "pdf", "filename": "report.pdf", "dataset_name": "Sales"}]
        return 404, {"error": {"message": f"no route for {path}"}}


def client_with_fake(**kwargs):
    api = FakeApi(**kwargs)
    return tatmaq_agent.TatmaqClient(
        "https://api.example.com", email="agent@example.com", password="secret", transport=api
    ), api


def test_client_signs_in_scopes_every_request_and_waits_for_the_job():
    client, api = client_with_fake()
    who = client.whoami()
    assert who["organisation"]["role"] == "agent" and who["config"]["ai_enabled"] is False
    assert client.datasets()[0]["latest_version"]["id"] == "v-1"
    job = client.analyse("v-1", PROMPT, wait=True)
    assert job["status"] == "completed"
    assert client.results("job-1")["findings"][0]["statement"] == "Sugar 2kg sold best."
    assert client.add_lesson("Compare branches.")["lessons"] == ["Compare branches."]
    assert api.logins == 1  # one sign-in, reused for every call
    assert ("POST", "/analysis-jobs") in api.calls and ("GET", "/analysis-jobs/job-1/results") in api.calls


def test_client_signs_in_again_once_when_the_token_expired():
    client, api = client_with_fake(expire_first_token=True)
    assert client.datasets()[0]["id"] == "ds-1"
    assert api.logins == 2


def test_client_reports_the_apis_own_message():
    client, _ = client_with_fake()
    with pytest.raises(tatmaq_agent.AgentError, match="no route"):
        client.dataset_profile("missing")


def test_cli_prints_json(monkeypatch, capsys):
    client, _ = client_with_fake()
    monkeypatch.setattr(tatmaq_agent, "client_from_env", lambda: client)
    assert tatmaq_agent.main(["--json", "datasets"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["name"] == "Sales"
    assert tatmaq_agent.main(["results", "job-1"]) == 0
    assert "Sugar 2kg sold best." in capsys.readouterr().out


# --------------------------------------------------------------------------- the MCP server


def test_mcp_initialize_and_tool_list():
    client, _ = client_with_fake()
    hello = tatmaq_mcp.handle(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert hello["result"]["serverInfo"]["name"] == "tatmaq-intelligence"
    assert hello["result"]["capabilities"] == {"tools": {}}
    tools = tatmaq_mcp.handle(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {"tatmaq_datasets", "tatmaq_analyse", "tatmaq_results", "tatmaq_add_lesson"} <= names
    assert all(tool["inputSchema"]["type"] == "object" for tool in tools)
    assert tatmaq_mcp.handle(client, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_mcp_calls_tools_and_reports_errors_as_tool_results():
    client, _ = client_with_fake()
    reply = tatmaq_mcp.handle(
        client,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "tatmaq_results", "arguments": {"job_id": "job-1"}},
        },
    )
    payload = json.loads(reply["result"]["content"][0]["text"])
    assert reply["result"]["isError"] is False and payload["summary"]["headline"] == "Sales were USD 36.50."

    failed = tatmaq_mcp.handle(
        client,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "tatmaq_dataset_profile", "arguments": {"dataset_id": "x"}},
        },
    )
    assert failed["result"]["isError"] is True and "no route" in failed["result"]["content"][0]["text"]

    missing = tatmaq_mcp.handle(
        client,
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "tatmaq_results", "arguments": {}}},
    )
    assert missing["result"]["isError"] is True and "Missing argument" in missing["result"]["content"][0]["text"]

    unknown = tatmaq_mcp.handle(client, {"jsonrpc": "2.0", "id": 6, "method": "tools/nope"})
    assert unknown["error"]["code"] == -32601


def test_mcp_serves_newline_delimited_json():
    import io

    client, _ = client_with_fake()
    stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n\nnot json\n')
    stdout = io.StringIO()
    tatmaq_mcp.serve(client, stdin, stdout)
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines[0]["result"] == {} and lines[1]["error"]["code"] == -32700
