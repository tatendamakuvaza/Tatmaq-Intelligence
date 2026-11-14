"""Acceptance: "Monetary calculations reconcile with independently calculated expected results"
and "Reports ... consistent with verified findings".

The benchmark dataset goes through the real pipeline (upload, import, clean, plan,
calculate, verify, report). Every figure must equal ``expected.json``, which the
generator computed separately in integer cents. Any future change to an agent that
alters a number fails here.
"""

from __future__ import annotations

import hashlib
import io
import re
from decimal import Decimal as D

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.core.database import system_session
from app.models import AgentRun
from conftest import new_account

PROMPT = "Analyse my sales records and identify my most profitable products."


@pytest.fixture(scope="module", params=["xlsx", "csv"])
def run(request, client, benchmark_xlsx, benchmark_csv):
    """One full analysis of the benchmark, once as Excel and once as CSV."""
    content = benchmark_xlsx if request.param == "xlsx" else benchmark_csv
    account = new_account(client, "Mopane Grocers (Pvt) Ltd")
    upload = account.upload(content, f"sales_benchmark.{request.param}")
    job = account.analyse(upload["dataset_version_id"], PROMPT)
    assert job["status"] == "completed", job
    with system_session() as session:
        output = session.scalar(select(AgentRun.output_json).where(
            AgentRun.job_id == job["id"], AgentRun.agent_key == "statistical_analysis", AgentRun.status == "completed"))  # fmt: skip
    return {"account": account, "upload": upload, "job": job, "content": content,
            "audit": output["outputs"]["audit"]["all"],
            "results": account.get(f"/analysis-jobs/{job['id']}/results").json()}  # fmt: skip


def money(table: dict) -> dict[str, D]:
    return {key: D(value) for key, value in table.items()}


def test_total_sales_matches_to_the_cent(run, expected):
    assert D(run["audit"]["sales"]["total"]) == D(expected["sales"]["total"])
    assert run["audit"]["sales"]["rows_used"] == expected["rows"]


def test_sales_by_month_product_branch_and_category_match(run, expected):
    sales = run["audit"]["sales"]
    assert {month: D(value) for month, value in sales["monthly"]} == money(expected["sales"]["by_month"])
    for dimension, key in (("Product", "by_product"), ("Branch", "by_branch"), ("Category", "by_category")):
        assert {name: D(value) for name, value in sales["dimensions"][dimension]} == money(expected["sales"][key]), (
            dimension
        )


def test_gross_profit_and_margin_match(run, expected):
    profit, want = run["audit"]["profitability"], expected["profitability"]
    assert D(profit["revenue"]) == D(want["revenue"]) and D(profit["cost"]) == D(want["cost"])
    assert D(profit["gross_profit"]) == D(want["gross_profit"])
    assert D(profit["margin_pct"]) == D(want["margin_pct"])
    assert profit["rows_used"] == want["rows_used"] and profit["rows_excluded"] == want["rows_missing_cost"]


def test_profit_by_product_and_by_month_match(run, expected):
    profit, want = run["audit"]["profitability"], expected["profitability"]
    by_product = {name: (D(revenue), D(cost)) for name, revenue, cost in profit["dimensions"]["Product"]}
    for name, figures in want["by_product"].items():
        revenue, cost = by_product[name]
        assert (revenue, cost, revenue - cost) == (
            D(figures["revenue"]),
            D(figures["cost"]),
            D(figures["gross_profit"]),
        ), name
    by_month = {month: D(revenue) - D(cost) for month, revenue, cost in profit["monthly"]}
    assert by_month == {month: D(figures["gross_profit"]) for month, figures in want["by_month"].items()}


def test_the_figures_shown_to_the_customer_are_the_verified_figures(run, expected):
    summary = run["results"]["summary"]
    kpis = {kpi["key"]: kpi["value"] for kpi in summary["segments"][0]["kpis"]}
    assert D(kpis["total_sales"]) == D(expected["sales"]["total"])
    assert D(kpis["gross_profit"]) == D(expected["profitability"]["gross_profit"])
    assert D(kpis["gross_margin"]) == D(expected["profitability"]["margin_pct"])
    assert kpis["invoices"] == expected["sales"]["invoices"] and D(kpis["units"]) == expected["sales"]["units"]
    assert summary["verification"]["passed"] and all(check["passed"] for check in summary["verification"]["checks"])
    assert len(summary["verification"]["checks"]) >= 15
    assert run["job"]["headline"].startswith(f"Total sales were USD {D(expected['sales']['total']):,.2f}")


def test_the_cleaning_agent_finds_every_planted_problem_and_deletes_nothing(run, expected):
    profile = run["account"].get(f"/datasets/{run['upload']['dataset_id']}/profile").json()
    cleaning, quality = profile["cleaning"], expected["quality"]
    issues = {(issue["code"], issue["column"]): issue["count"] for issue in cleaning["issues"]}
    changes = {(entry["step"], entry["column"]): entry["rows_affected"] for entry in cleaning["log"]}

    assert (
        cleaning["rows_in"] == expected["rows"] + expected["summary_rows"]
    )  # the TOTAL line is the only row set aside
    assert cleaning["rows_out"] == profile["version"]["row_count"] == expected["rows"]
    assert cleaning["duplicates"]["rows"] == issues[("duplicate_rows", None)] == quality["duplicate_rows"]
    assert D(cleaning["duplicates"]["revenue"]) == D(quality["duplicate_sales"])
    assert issues[("missing_values", "Quantity")] == quality["missing_quantity"]
    assert issues[("invalid_numbers", "Quantity")] == quality["invalid_quantity"]
    assert issues[("missing_values", "Cost of Sales")] == quality["missing_cost"]
    assert issues[("negative_values", "Sales Amount")] == quality["negative_lines"]
    assert changes[("standardise_dates", "Date")] == quality["text_dates"]
    assert changes[("normalise_numbers", "Sales Amount")] == quality["text_amounts"]
    assert changes[("standardise_categories", "Branch")] == quality["branch_case_variants"]
    assert changes[("trim_whitespace", "Branch")] == quality["branch_stray_spaces"]
    assert ("ambiguous_dates", "Date") not in issues  # dates like 25/03/2026 settle the day-first question
    branch = next(column for column in profile["columns"] if column["name"] == "Branch")
    assert branch["distinct_count"] == 5  # four spellings of Harare CBD became one


def test_the_file_fingerprint_is_recorded_and_every_finding_cites_it(run):
    digest = hashlib.sha256(run["content"]).hexdigest()
    assert (
        run["account"].get(f"/datasets/{run['upload']['dataset_id']}").json()["latest_version"]["sha256_hash"] == digest
    )
    findings = run["results"]["findings"]
    assert len(findings) >= 12 and all(finding["approved"] for finding in findings)
    for finding in findings:
        evidence = finding["evidence"]
        assert evidence["ref"] == finding["evidence_ref"] and evidence["dataset_sha256"] == digest
        assert evidence["dataset_version_id"] == run["upload"]["dataset_version_id"]
        assert evidence["formula"] and evidence["operation"]


def test_all_three_reports_carry_the_verified_figures(run, expected):
    account, total = run["account"], D(expected["sales"]["total"])
    files = {}
    for report in run["results"]["reports"]:
        link = account.get(f"/reports/{report['id']}/download").json()
        response = account.client.get(link["url"])
        assert response.status_code == 200 and len(response.content) == report["size_bytes"]
        files[report["format"]] = response.content
    assert set(files) == {"pdf", "xlsx", "html"} and files["pdf"].startswith(b"%PDF")

    html = files["html"].decode()
    for figure in (f"USD {total:,.2f}", f"USD {D(expected['profitability']['gross_profit']):,.2f}",
                   f"{D(expected['profitability']['margin_pct']):.2f}%"):  # fmt: skip
        assert figure in html
    assert "<script" not in html.lower() and "http://" not in html.replace("http://www.w3.org", "")

    workbook = load_workbook(io.BytesIO(files["xlsx"]))
    summary = {row[0]: row[1] for row in workbook["Summary"].iter_rows(values_only=True) if row[0]}
    assert D(str(summary["Total sales"])) == total
    assert D(str(summary["Gross profit"])) == D(expected["profitability"]["gross_profit"])
    by_product = {
        row[0]: row[1] for row in workbook["Sales by Product"].iter_rows(min_row=2, values_only=True) if row[0]
    }
    top = max(expected["sales"]["by_product"].items(), key=lambda item: D(item[1]))
    assert D(str(by_product[top[0]])) == D(top[1])
    # every number in the summary bullets is a verified figure
    statements = " ".join(f["statement"] for f in run["results"]["findings"])
    for bullet in run["results"]["summary"]["executive_summary"]:
        for number in re.findall(r"\d[\d,]*\.\d+", bullet):
            assert number in statements


def test_excel_and_csv_versions_of_the_same_data_give_identical_results(client, benchmark_xlsx, benchmark_csv):
    account = new_account(client, "Format Check")
    headlines = set()
    for content, name in ((benchmark_xlsx, "a.xlsx"), (benchmark_csv, "b.csv")):
        upload = account.upload(content, name)
        job = account.analyse(upload["dataset_version_id"], PROMPT)
        results = account.get(f"/analysis-jobs/{job['id']}/results").json()
        headlines.add(tuple(finding["statement"] for finding in results["findings"]))
    assert len(headlines) == 1
