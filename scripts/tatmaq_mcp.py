#!/usr/bin/env python3
"""Expose a TATMAQ Intelligence installation as MCP tools, over stdio. Standard library only.

Any MCP client (Claude Desktop, Cursor, and others) can then read your datasets, run
analyses and quote the verified findings. Configure it with the same environment
variables as scripts/tatmaq_agent.py:

    {
      "mcpServers": {
        "tatmaq": {
          "command": "python",
          "args": ["C:/Users/Admin/Tatmaq-Intelligence/scripts/tatmaq_mcp.py"],
          "env": {
            "TATMAQ_API_URL": "https://tatmaq-api.onrender.com",
            "TATMAQ_EMAIL": "arena-agent@example.com",
            "TATMAQ_PASSWORD": "...",
            "TATMAQ_ORGANISATION_ID": "..."
          }
        }
      }
    }

Arena's Agent Mode does not take a custom MCP connector: there, use
scripts/tatmaq_agent.py from the sandbox instead. The tools are the same.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path[:0] = [str(Path(__file__).resolve().parent)]

from tatmaq_agent import AgentError, TatmaqClient, client_from_env  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "tatmaq-intelligence", "version": "1.0.0"}

_STRING = {"type": "string"}


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOLS = [
    _tool(
        "tatmaq_whoami",
        "The account, organisation, permissions and server configuration this bridge is connected to.",
        {},
        [],
    ),
    _tool("tatmaq_datasets", "List datasets with their latest version ids, row counts and status.", {}, []),
    _tool(
        "tatmaq_dataset_profile",
        "Column dictionary, data-quality findings and cleaning log for one dataset.",
        {"dataset_id": _STRING},
        ["dataset_id"],
    ),
    _tool(
        "tatmaq_analyse",
        "Run a verified analysis. Returns a job id; set wait to true to poll until it finishes.",
        {
            "dataset_version_id": _STRING,
            "prompt": _STRING,
            "analysis_type": {
                "type": "string",
                "enum": ["automatic", "sales", "profitability", "statistical", "data_quality"],
            },
            "wait": {"type": "boolean"},
        },
        ["dataset_version_id", "prompt"],
    ),
    _tool(
        "tatmaq_job",
        "Agent-by-agent progress, summaries and warnings for one analysis.",
        {"job_id": _STRING},
        ["job_id"],
    ),
    _tool(
        "tatmaq_results",
        "The verified findings, figures, charts, tables and reports of one analysis. Quote only these figures.",
        {"job_id": _STRING},
        ["job_id"],
    ),
    _tool("tatmaq_reports", "List the report files (PDF, Excel, HTML) that exist.", {}, []),
    _tool(
        "tatmaq_learning",
        "Read the organisation's learning profile: business context, glossary, preferences and lessons.",
        {},
        [],
    ),
    _tool(
        "tatmaq_add_lesson",
        "Record a short lesson the agents should apply to future analyses.",
        {"lesson": _STRING, "source": _STRING},
        ["lesson"],
    ),
    _tool(
        "tatmaq_feedback",
        "Rate a completed analysis, optionally with a lesson.",
        {"job_id": _STRING, "rating": {"type": "string", "enum": ["helpful", "not_helpful"]}, "lesson": _STRING},
        ["job_id", "rating"],
    ),
]


def call_tool(client: TatmaqClient, name: str, arguments: dict[str, Any]) -> Any:
    if name == "tatmaq_whoami":
        return client.whoami()
    if name == "tatmaq_datasets":
        return client.datasets()
    if name == "tatmaq_dataset_profile":
        return client.dataset_profile(arguments["dataset_id"])
    if name == "tatmaq_analyse":
        return client.analyse(
            arguments["dataset_version_id"],
            arguments["prompt"],
            analysis_type=arguments.get("analysis_type", "automatic"),
            wait=bool(arguments.get("wait", False)),
        )
    if name == "tatmaq_job":
        return client.job(arguments["job_id"])
    if name == "tatmaq_results":
        return client.results(arguments["job_id"])
    if name == "tatmaq_reports":
        return client.reports()
    if name == "tatmaq_learning":
        return client.learning()
    if name == "tatmaq_add_lesson":
        return client.add_lesson(arguments["lesson"], arguments.get("source"))
    if name == "tatmaq_feedback":
        return client.feedback(arguments["job_id"], arguments["rating"], arguments.get("lesson"))
    raise AgentError(f"Unknown tool: {name}")


def handle(client: TatmaqClient, message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    method, message_id = message.get("method"), message.get("id")
    if method is None or str(method).startswith("notifications/"):
        return None
    result: Any
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}}, "serverInfo": SERVER_INFO}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            data = call_tool(client, params.get("name", ""), params.get("arguments") or {})
            result = {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
                "isError": False,
            }
        except AgentError as error:
            result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
        except KeyError as error:
            result = {"content": [{"type": "text", "text": f"Missing argument: {error}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": message_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def serve(client: TatmaqClient, stdin=sys.stdin, stdout=sys.stdout) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            stdout.write(
                json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}) + "\n"
            )
            stdout.flush()
            continue
        response = handle(client, message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve(client_from_env())
