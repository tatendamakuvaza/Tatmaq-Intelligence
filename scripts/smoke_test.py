#!/usr/bin/env python3
"""End-to-end check of a running installation, over HTTP, exactly as a customer would use it.

    python scripts/smoke_test.py                                   # local API on :8000
    python scripts/smoke_test.py --base-url http://localhost:3000/api   # through the web app's proxy
    python scripts/smoke_test.py --base-url https://api.example.com --token <access token>

Signs up (development sign-in) or uses the token you pass (Supabase), creates an
organisation, uploads the sample dataset, waits for it to be imported, runs an
analysis, checks the headline figure against the benchmark and downloads the PDF.
Exits non-zero on the first failure. Run it after every deployment.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK = REPO_ROOT / "apps" / "api" / "tests" / "benchmark"
PROMPT = "Analyse my sales records and identify my most profitable products."


def step(message: str) -> None:
    print(f"  ok  {message}")


def fail(message: str) -> None:
    print(f"FAIL  {message}", file=sys.stderr)
    raise SystemExit(1)


def check(response: httpx.Response, expected: int = 200) -> dict:
    if response.status_code != expected:
        fail(f"{response.request.method} {response.request.url.path} -> {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else {}


def wait_for(client: httpx.Client, path: str, done, timeout: float, what: str) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = check(client.get(path))
        if done(body):
            return body
        time.sleep(1)
    fail(f"timed out after {timeout:.0f}s waiting for {what} (is the worker running?)")
    raise AssertionError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", help="access token of an existing user (required when the API uses Supabase Auth)")
    parser.add_argument("--email", help="sign in to this existing account instead of creating a throwaway one")
    parser.add_argument("--password", help="the password for --email")
    parser.add_argument("--timeout", type=float, default=120)
    arguments = parser.parse_args()
    base = arguments.base_url.rstrip("/")
    expected = json.loads((BENCHMARK / "expected.json").read_text())
    started = time.monotonic()

    with httpx.Client(base_url=f"{base}/v1", timeout=60) as client:
        config = check(client.get("/config"))
        step(
            f"API {config['version']} is up (sign-in: {config['auth_mode']}, AI model: {'on' if config['ai_enabled'] else 'off'})"
        )

        token = arguments.token
        if not token and arguments.email:
            if not arguments.password:
                fail("--email needs --password")
            token = check(client.post("/auth/login", json={"email": arguments.email, "password": arguments.password}))[
                "access_token"
            ]
            step(f"signed in as {arguments.email}")
        if not token:
            if config["auth_mode"] == "supabase":
                fail("this API uses Supabase Auth: pass --token with a signed-in user's access token")
            if not config.get("signups_open", True):
                fail("sign-ups are closed on this server: pass --email and --password of an existing account")
            email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"
            token = check(client.post("/auth/register", json={"email": email, "password": uuid.uuid4().hex}), 201)[
                "access_token"
            ]
            step(f"registered {email}")
        client.headers["Authorization"] = f"Bearer {token}"
        check(client.post("/auth/profile", json={"full_name": "Smoke Test"}))

        created = check(client.post("/organisations", json={"name": f"Smoke Test {uuid.uuid4().hex[:6]}"}), 201)
        client.headers["X-Organisation-Id"] = created["organisation"]["id"]
        workspace = created["workspace"]["id"]
        step("created an organisation and workspace")

        content = (BENCHMARK / "sales_benchmark.xlsx").read_bytes()
        target = check(client.post("/datasets/upload-url", json={
            "workspace_id": workspace, "filename": "sales_benchmark.xlsx", "size_bytes": len(content)}), 201)  # fmt: skip
        upload = target["upload"]
        url = f"{base}{upload['url']}" if upload["url"].startswith("/") else upload["url"]
        sent = httpx.request(upload["method"], url, content=content, headers=upload["headers"], timeout=120)
        if sent.status_code not in (200, 201, 204):
            fail(f"upload -> {sent.status_code}: {sent.text[:300]}")
        completed = check(client.post(f"/datasets/{target['dataset_id']}/complete"))
        step(f"uploaded {len(content):,} bytes")

        dataset = wait_for(client, f"/datasets/{target['dataset_id']}", lambda d: d["status"] in ("ready", "failed"),
                           arguments.timeout, "the dataset to be imported")  # fmt: skip
        if dataset["status"] != "ready":
            fail(f"import failed: {dataset['error_message']}")
        if dataset["latest_version"]["row_count"] != expected["rows"]:
            fail(f"imported {dataset['latest_version']['row_count']} rows, expected {expected['rows']}")
        step(f"imported and cleaned {expected['rows']:,} rows")

        accepted = check(client.post("/analysis-jobs", headers={"Idempotency-Key": str(uuid.uuid4())}, json={
            "workspace_id": workspace, "dataset_version_id": completed["dataset_version_id"], "prompt": PROMPT}), 202)  # fmt: skip
        job = wait_for(client, f"/analysis-jobs/{accepted['job_id']}", lambda j: j["is_finished"], arguments.timeout,
                       "the analysis to finish")  # fmt: skip
        if job["status"] != "completed":
            fail(f"analysis ended as {job['status']}: {job['error_message']}")
        step("analysis completed")

        results = check(client.get(f"/analysis-jobs/{accepted['job_id']}/results"))
        kpis = {kpi["key"]: kpi["value"] for kpi in results["summary"]["segments"][0]["kpis"]}
        for key, want in (("total_sales", expected["sales"]["total"]), ("gross_profit", expected["profitability"]["gross_profit"]),
                          ("gross_margin", expected["profitability"]["margin_pct"])):  # fmt: skip
            if kpis.get(key) != want:
                fail(f"{key} is {kpis.get(key)}, the benchmark answer is {want}")
        checks = results["summary"]["verification"]["checks"]
        if not all(item["passed"] for item in checks):
            fail("a verification check failed")
        step(f"figures match the benchmark to the cent; {len(checks)} verification checks passed")

        pdf = next(report for report in results["reports"] if report["format"] == "pdf")
        link = check(client.get(f"/reports/{pdf['id']}/download"))
        url = f"{base}{link['url']}" if link["url"].startswith("/") else link["url"]
        document = httpx.get(url, timeout=60, follow_redirects=True)
        if document.status_code != 200 or not document.content.startswith(b"%PDF"):
            fail(f"report download -> {document.status_code}")
        step(f"downloaded {link['filename']} ({len(document.content):,} bytes)")

    print(f"PASS  in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
