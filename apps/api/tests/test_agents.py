"""Each agent's acceptance test (specification Part J), plus the rules that bound what agents may do."""

from __future__ import annotations

import io
import uuid

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.agents.base import Toolbox, ToolPermissionError
from app.agents.base import permissions as p
from app.agents.chief_intelligence.planner import (
    Column,
    PlanningError,
    build_execution_plan,
    plan_with_rules,
    validate_plan,
)
from app.agents.data_acquisition.csv_reader import detect_delimiter, read_csv
from app.agents.data_acquisition.excel_reader import read_xlsx
from app.agents.data_acquisition.profiler import profile_table
from app.agents.orchestration import routing
from app.core.database import system_session
from app.llm import LLMError, LLMResponse
from app.models import AgentRun, UsageRecord

PROMPT = "Analyse my sales records and identify my most profitable products."


# --------------------------------------------------------------------------- Agent 02: acquisition


def test_excel_import_finds_the_right_sheet_header_and_row_numbers(tmp_path):
    workbook = Workbook()
    notes = workbook.active
    notes.title = "Notes"
    notes["A1"] = "see the other sheet"
    sheet = workbook.create_sheet("Register")
    sheet["A1"] = "Sales register 2026"
    sheet.append([])
    sheet.append(["Invoice No", "Date", "Amount"])
    from datetime import datetime

    sheet.append([1001, datetime(2026, 9, 1), 1250.5])
    sheet.append([])
    sheet.append([1002, "02/09/2026", "1,000.00"])
    path = tmp_path / "book.xlsx"
    workbook.save(path)

    table = read_xlsx(path, max_rows=100, max_columns=10)
    assert table.source["sheet"] == "Register" and table.source["header_row"] == 3
    assert table.columns == ["Invoice No", "Date", "Amount"]
    assert table.frame["__row__"].tolist() == [4, 6]  # the spreadsheet's own row numbers; the blank row is skipped
    assert table.frame["Date"].tolist() == ["2026-09-01", "02/09/2026"]  # a real date cell, and a date typed as text
    assert table.frame["Amount"].tolist() == ["1250.5", "1,000.00"]
    assert "not analysed: 'Notes'" in table.log[0]


def test_csv_import_detects_separator_encoding_and_missing_headers(tmp_path):
    assert detect_delimiter("a;b;c\n1;2;3\n") == ";" and detect_delimiter("a\tb\n1\t2\n") == "\t"
    semicolon = tmp_path / "sa.csv"
    semicolon.write_bytes("Produit;Montant\nCaf\xe9;1 234,56\nTh\xe9;12,5\n".encode("cp1252"))
    table = read_csv(semicolon, max_rows=10, max_columns=5)
    assert table.source == {"type": "csv", "encoding": "windows-1252", "delimiter": "semicolon", "header_row": 1}
    assert table.frame["Produit"].tolist() == ["Café", "Thé"] and "not saved as UTF-8" in table.warnings[0]
    amount = next(column for column in profile_table(table).columns if column.name == "Montant")
    assert amount.kind == "number" and amount.ctype.decimal_separator == "," and amount.stats["max"] == 1234.56

    headless = tmp_path / "headless.csv"
    headless.write_text("1,2026-01-05,10.5\n2,2026-01-06,11.5\n")
    table = read_csv(headless, max_rows=10, max_columns=5)
    assert table.columns == ["Column 1", "Column 2", "Column 3"] and len(table.frame) == 2
    assert "No header row was found" in table.warnings[0]


@pytest.mark.parametrize(("headers", "expected"), [
    (["Invoice No", "Invoice Date", "Customer Name", "Item Description", "Qty", "Unit Price", "Total"],
     {"identifier": "Invoice No", "date": "Invoice Date", "customer": "Customer Name", "product": "Item Description",
      "quantity": "Qty", "unit_price": "Unit Price", "revenue": "Total"}),
    (["Date", "Product", "Units Sold", "Selling Price", "Cost Price", "Sales Rep"],
     {"date": "Date", "product": "Product", "quantity": "Units Sold", "unit_price": "Selling Price",
      "unit_cost": "Cost Price", "salesperson": "Sales Rep"}),
    (["Period", "Branch", "Net Sales", "Gross Amount", "COGS", "VAT Amount", "Sales Target"],
     {"date": "Period", "region": "Branch", "revenue": "Net Sales", "cost": "COGS"}),
    (["Order ID", "Order Date", "Due Date", "Category", "Customer Type", "Amount", "Currency"],
     {"identifier": "Order ID", "date": "Order Date", "category": "Category", "revenue": "Amount", "currency": "Currency"}),
])  # fmt: skip
def test_column_roles_are_recognised_from_typical_headings(tmp_path, headers, expected):
    samples = {"identifier": "A-1001", "date": "15/03/2026", "customer": "Chipo Stores", "product": "Sugar 2kg",
               "quantity": "4", "unit_price": "2.60", "unit_cost": "2.08", "revenue": "10.40", "cost": "8.32",
               "region": "Harare", "category": "Groceries", "currency": "USD", "salesperson": "Tariro"}  # fmt: skip
    values = []
    for header in headers:
        role = next((role for role, name in expected.items() if name == header), None)
        values.append(
            samples.get(role, "15/04/2026" if "Date" in header else ("Retail" if "Type" in header else "7.50"))
        )
    path = tmp_path / "roles.csv"
    path.write_text(",".join(headers) + "\n" + ("\n".join([",".join(values)] * 3)) + "\n")
    profile = profile_table(read_csv(path, max_rows=10, max_columns=20))
    assert profile.roles == expected
    by_name = {column.name: column for column in profile.columns}
    for other in ("Gross Amount", "VAT Amount", "Sales Target"):  # numbers that are not *the* sales figure
        if other in by_name:
            assert by_name[other].role == "measure"
    if "Due Date" in by_name:
        assert by_name["Due Date"].role == "date_other"


def test_a_heading_only_suggests_a_role_the_values_must_agree(tmp_path):
    path = tmp_path / "misleading.csv"
    path.write_text(
        "Amount,Invoice No,Sales Date\nto be confirmed,00017,soon\npending,00018,later\nnot yet,00019,tbc\n"
    )
    columns = {c.name: c for c in profile_table(read_csv(path, max_rows=10, max_columns=5)).columns}
    assert (columns["Amount"].kind, columns["Amount"].role) == ("text", "dimension")  # words are not money
    assert columns["Invoice No"].kind == "text" and columns["Invoice No"].examples == ["00017", "00018", "00019"]
    assert columns["Sales Date"].kind == "text"


# --------------------------------------------------------------------------- Agent 01: planning

SALES_COLUMNS = [
    Column("Invoice No", "text", "identifier", 900, 1000), Column("Date", "date", "date", 300, 1000),
    Column("Branch", "text", "region", 5, 1000), Column("Product", "text", "product", 18, 1000),
    Column("Quantity", "number", "quantity", 20, 990), Column("Sales Amount", "number", "revenue", 200, 1000),
    Column("Cost of Sales", "number", "cost", 250, 990),
]  # fmt: skip


@pytest.mark.parametrize(("prompt", "operations"), [
    ("Analyse my sales records and identify my most profitable products.", ["sales_overview", "profitability"]),
    ("Determine why our gross profit margin declined between January and June.", ["sales_overview", "profitability"]),
    ("Analyse this company's sales performance for the past 12 months.", ["sales_overview"]),
    ("Is quantity correlated with sales amount?", ["correlation"]),
    ("Are there any unusual transactions?", ["outliers"]),
    ("How clean is this file? Any duplicates?", ["data_quality"]),
])  # fmt: skip
def test_the_chief_plans_the_right_analyses_for_typical_requests(prompt, operations):
    outcome = plan_with_rules(prompt, "automatic", SALES_COLUMNS)
    assert [operation.type for operation in outcome.spec.operations] == operations
    if operations[0] == "sales_overview":
        sales = outcome.spec.operations[0]
        assert (sales.revenue.column, sales.date, sales.document) == ("Sales Amount", "Date", "Invoice No")


def test_the_chief_puts_the_dimension_asked_about_first_and_says_what_it_cannot_do():
    assert (
        plan_with_rules("Which branches sell the most?", "automatic", SALES_COLUMNS).spec.operations[0].dimensions[0]
        == "Branch"
    )
    without_cost = [column for column in SALES_COLUMNS if column.role != "cost"]
    outcome = plan_with_rules("most profitable products", "automatic", without_cost)
    assert [operation.type for operation in outcome.spec.operations] == ["sales_overview"]
    assert "no cost column" in outcome.notes[0]
    with pytest.raises(PlanningError, match="Rename the relevant column headings"):
        plan_with_rules("profit by product", "automatic", [Column("Notes", "text", "text", 10, 10)])


def test_a_task_plan_naming_unknown_agents_or_actions_is_rejected():
    assert validate_plan(build_execution_plan()) == []
    problems = validate_plan([
        {"sequence": 1, "agent": "shell", "action": "run"},
        {"sequence": 2, "agent": "data_cleaning", "action": "delete_rows", "depends_on": [7]},
        {"sequence": 2, "agent": "statistical_analysis", "action": "run_analysis"},
    ])  # fmt: skip
    assert len(problems) == 4 and "unknown agent 'shell'" in problems[0] and "no action 'delete_rows'" in problems[1]


def test_routing_covers_every_path():
    assert routing.after_preflight({"status": "failed"}) == "finalise" and routing.after_preflight({}) == "planning"
    assert routing.after_cleaning({"cleaning_result": {"outputs": {"infeasible": []}}}) == "statistics"
    assert routing.after_cleaning({"cleaning_result": {"outputs": {"infeasible": ["regression"]}}}) == "planning"
    assert (
        routing.after_cleaning({"status": "failed", "cleaning_result": {"outputs": {"infeasible": ["x"]}}})
        == "finalise"
    )
    assert routing.after_verification({"verification_result": {"outputs": {"passed": True}}}) == "reporting"
    assert routing.after_verification({"verification_result": {"outputs": {"passed": False}}}) == "statistics"
    assert routing.after_verification({"status": "failed"}) == "finalise"


# --------------------------------------------------------------------------- tool permissions


def test_agents_can_only_reach_the_tools_they_are_granted():
    tools = {name: object() for name in (p.TOOL_ORIGINAL_READ, p.TOOL_RAW_READ, p.TOOL_RAW_WRITE, p.TOOL_CLEANED_READ,
                                         p.TOOL_CLEANED_WRITE, p.TOOL_LLM, p.TOOL_ARTIFACT_WRITE)}  # fmt: skip
    statistical, chief, report = (
        Toolbox(key, tools) for key in ("statistical_analysis", "chief_intelligence", "report_generation")
    )
    assert statistical.permitted == (p.TOOL_CLEANED_READ,)  # the calculator has a dataset reader and nothing else
    for forbidden in (p.TOOL_LLM, p.TOOL_CLEANED_WRITE, p.TOOL_ORIGINAL_READ, p.TOOL_ARTIFACT_WRITE):
        with pytest.raises(ToolPermissionError):
            statistical.get(forbidden)
    for agent in (chief, report):  # the two agents that may use an AI model can never read customer rows
        for forbidden in (p.TOOL_CLEANED_READ, p.TOOL_RAW_READ, p.TOOL_ORIGINAL_READ):
            with pytest.raises(ToolPermissionError):
                agent.get(forbidden)
    assert not any("write" in tool and "original" in tool for tool in tools)  # nothing can write an original
    with pytest.raises(ToolPermissionError):
        Toolbox("unknown_agent", tools).get(p.TOOL_LLM)


def test_tools_refuse_objects_outside_their_organisation_or_purpose(tmp_path):
    from app.agents.base.tools import build_tools
    from app.storage import LocalStorage, TenantBoundaryError
    from app.storage.base import StorageError

    mine, theirs, job = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tools = build_tools(
        storage=LocalStorage(tmp_path / "s", "k"), organisation_id=mine, job_id=job, workdir=tmp_path / "w", llm=None
    )
    with pytest.raises(TenantBoundaryError):
        tools[p.TOOL_CLEANED_READ](f"org/{theirs}/datasets/x/v1/cleaned.parquet")
    with pytest.raises(TenantBoundaryError):
        tools[p.TOOL_ORIGINAL_READ](f"org/{theirs}/datasets/x/v1/original.csv")
    with pytest.raises(StorageError, match="only handles"):
        tools[p.TOOL_CLEANED_READ](f"org/{mine}/datasets/x/v1/raw.parquet")
    with pytest.raises(StorageError, match="outside its own job"):
        tools[p.TOOL_ARTIFACT_WRITE](f"org/{mine}/jobs/{uuid.uuid4()}/report.pdf", tmp_path / "x", "application/pdf")


# --------------------------------------------------------------------------- AI model in the loop


class FakeLLM:
    """Stands in for an AI provider: returns scripted JSON and records what it was sent."""

    provider, model = "fake", "fake-model-1"

    def __init__(self, plan=None, narrative=None, replan=None):
        self.plan, self.narrative, self.replan, self.calls = plan, narrative, replan, []

    async def complete_json(self, *, system: str, user: str, max_output_tokens: int = 2000) -> LLMResponse:
        self.calls.append({"system": system, "user": user})
        planning = "planning component" in system
        reply = self.plan if planning else self.narrative
        if planning and self.replan is not None and "Do not use these operations" in user:
            reply = self.replan
        if isinstance(reply, Exception):
            raise reply
        return LLMResponse(data=reply, model=self.model, tokens_input=120, tokens_output=45)


AI_PLAN = {
    "objective": "Find the most profitable products.", "report_title": "Product Profitability Review",
    "currency_column": None,
    "operations": [
        {"type": "sales_overview", "revenue": {"column": "Sales Amount"}, "date": "Date", "dimensions": ["Product"],
         "quantity": "Quantity", "document": "Invoice No"},
        {"type": "profitability", "revenue": {"column": "Sales Amount"}, "cost": {"column": "Cost of Sales"},
         "date": "Date", "dimensions": ["Product"]},
    ],
}  # fmt: skip


@pytest.fixture
def with_llm(monkeypatch):
    def install(llm: FakeLLM) -> FakeLLM:
        monkeypatch.setattr("app.workers.runner.build_llm", lambda settings: llm)
        return llm

    return install


def report_task(account, job_id) -> dict:
    return account.get(f"/analysis-jobs/{job_id}/agents").json()["tasks"][-1]


def test_an_ai_plan_is_validated_then_used_and_the_model_never_sees_customer_rows(account, small_csv, with_llm):
    llm = with_llm(FakeLLM(plan=AI_PLAN, narrative={
        "executive_summary": ["Total sales were USD 36.50 from 6 invoices.", "Gross profit was USD 9.70, a margin of 26.6%."],
        "next_steps": ["Review pricing on the lowest-margin product."]}))  # fmt: skip
    job = account.analyse(account.upload(small_csv)["dataset_version_id"], PROMPT)
    summary = account.get(f"/analysis-jobs/{job['id']}/results").json()["summary"]
    assert job["status"] == "completed" and summary["plan"]["planner"] == "ai"
    assert summary["title"] == "Product Profitability Review"
    assert summary["executive_summary"][0] == "Total sales were USD 36.50 from 6 invoices."
    assert "fake-model-1" in summary["narrative_source"] and "checked against" in summary["narrative_source"]

    sent = " ".join(call["user"] for call in llm.calls)
    assert '"name": "Sales Amount"' in sent  # column names and types are shared...
    for row_value in ("Harare", "Mutare", "A1", "Rice 2kg", "17/01/2026"):  # ...but no cell of customer data
        assert row_value not in llm.calls[0]["user"]
    with system_session() as session:
        tokens = session.scalar(
            select(UsageRecord.quantity).where(UsageRecord.job_id == job["id"], UsageRecord.metric == "ai_tokens")
        )
        models = set(
            session.scalars(
                select(AgentRun.model_name).where(AgentRun.job_id == job["id"], AgentRun.model_name.is_not(None))
            )
        )
    assert tokens == 330 and models == {"fake-model-1"}  # two calls of 120 + 45 tokens, accounted for


@pytest.mark.parametrize(("draft", "reason"), [
    ({"executive_summary": ["Total sales were USD 36.50.", "Profit should reach USD 99,999.99 next year."], "next_steps": []},
     "figures that are not in the verified results (99999.99)"),
    ({"executive_summary": ["Total sales were USD 36.50.", "The Mutare branch is committing fraud."], "next_steps": []},
     "an allegation the evidence cannot support"),
    ({"summary": "wrong shape"}, "not in the required form"),
    (LLMError("AI provider returned 401: bad key"), "unavailable"),
])  # fmt: skip
def test_an_ai_draft_with_an_invented_figure_or_an_allegation_never_reaches_the_report(
    account, small_csv, with_llm, draft, reason
):
    with_llm(FakeLLM(plan=AI_PLAN, narrative=draft))
    job = account.analyse(account.upload(small_csv)["dataset_version_id"], PROMPT)
    results = account.get(f"/analysis-jobs/{job['id']}/results").json()
    assert job["status"] == "completed"
    assert reason in " ".join(report_task(account, job["id"])["warnings"])
    assert results["summary"]["narrative_source"] == "Written from the verified findings using fixed templates."
    link = account.get(f"/reports/{next(r['id'] for r in results['reports'] if r['format'] == 'html')}/download").json()
    html = account.client.get(link["url"]).text
    assert "99,999.99" not in html and "fraud" not in html.lower() and "USD 36.50" in html


@pytest.mark.parametrize("bad_plan", [
    {**AI_PLAN, "operations": [{"type": "sales_overview", "revenue": {"column": "Turnover (made up)"}}]},
    {**AI_PLAN, "operations": [{"type": "execute_sql", "query": "DROP TABLE datasets"}]},
    {**AI_PLAN, "operations": [{"type": "sales_overview", "revenue": {"column": "Branch"}}]},
    {"result": "Total sales are USD 1,000,000"},
    LLMError("timeout"),
])  # fmt: skip
def test_an_ai_plan_that_does_not_fit_the_data_is_discarded_for_the_built_in_planner(
    account, small_csv, with_llm, bad_plan
):
    with_llm(FakeLLM(plan=bad_plan, narrative=LLMError("off")))
    job = account.analyse(account.upload(small_csv)["dataset_version_id"], PROMPT)
    assert job["status"] == "completed" and "USD 36.50" in job["headline"]
    tasks = account.get(f"/analysis-jobs/{job['id']}/agents").json()["tasks"]
    assert "built-in planner" in tasks[0]["summary"] and "built-in planner was used instead" in " ".join(
        tasks[0]["warnings"]
    )
    assert account.get(f"/analysis-jobs/{job['id']}/results").json()["summary"]["plan"]["planner"] == "rules"


def test_a_plan_the_data_cannot_support_goes_back_to_the_chief_once(account, with_llm):
    content = ("Invoice No,Date,Product,Sales Amount,Discount\n" +
               "".join(f"A{i},{i + 1:02d}/03/2026,Sugar,{10 + i}.00,{'1.5' if i < 2 else ''}\n" for i in range(12))).encode()  # fmt: skip
    regression = {"type": "regression", "target": "Sales Amount", "predictors": ["Discount"]}
    sales = {"type": "sales_overview", "revenue": {"column": "Sales Amount"}, "date": "Date", "dimensions": []}
    plan = {"objective": "o", "report_title": "Drivers of sales", "operations": [sales, regression]}
    with_llm(FakeLLM(plan=plan, replan={**plan, "operations": [sales]}, narrative=LLMError("off")))
    job = account.analyse(account.upload(content)["dataset_version_id"], "What drives sales?")
    assert job["status"] == "completed"
    tasks = account.get(f"/analysis-jobs/{job['id']}/agents").json()["tasks"]
    assert (tasks[0]["attempts"], tasks[2]["attempts"]) == (2, 2)  # planned twice, validated twice
    operations = account.get(f"/analysis-jobs/{job['id']}/results").json()["summary"]["plan"]["operations"]
    assert [operation["type"] for operation in operations] == ["sales_overview"]


# --------------------------------------------------------------------------- Agents 03-05 through the pipeline


def test_amounts_in_different_currencies_are_never_added_together(account):
    content = (b"Date,Product,Currency,Sales Amount,Cost of Sales\n"
               b"05/01/2026,Sugar,USD,10.10,8.00\n06/01/2026,Rice,usd,20.20,15.00\n"
               b"07/01/2026,Sugar,ZiG,300.30,250.00\n08/01/2026,Rice,ZWG,400.40,310.00\n09/01/2026,Salt,ZWG,50.05,30.00\n")  # fmt: skip
    job = account.analyse(account.upload(content)["dataset_version_id"], PROMPT)
    results = account.get(f"/analysis-jobs/{job['id']}/results").json()
    segments = {segment["key"]: segment for segment in results["summary"]["segments"]}
    assert set(segments) == {"USD", "ZWG"}  # "usd" and "ZiG" are recognised as USD and ZWG
    totals = {
        key: next(k["value"] for k in segment["kpis"] if k["key"] == "total_sales") for key, segment in segments.items()
    }
    assert totals == {"USD": "30.30", "ZWG": "750.75"}
    assert not any(
        "781.05" in finding["statement"] for finding in results["findings"]
    )  # 30.30 + 750.75 appears nowhere
    assert any("analysed separately and never added together" in warning for warning in results["summary"]["warnings"])
    assert {finding["evidence"]["segment"] for finding in results["findings"]} == {"USD", "ZWG"}
    assert any(check["name"].startswith("ZWG: ") for check in results["summary"]["verification"]["checks"])


def test_sales_and_cost_are_derived_from_quantity_when_there_are_no_total_columns(account):
    content = (b"Date,Product,Qty,Unit Price,Unit Cost\n05/01/2026,Sugar,3,19.99,15.10\n06/01/2026,Rice,7,0.10,0.07\n"
               b"07/01/2026,Salt,,5.00,3.00\n")  # fmt: skip
    job = account.analyse(account.upload(content)["dataset_version_id"], PROMPT)
    results = account.get(f"/analysis-jobs/{job['id']}/results").json()
    kpis = {kpi["key"]: kpi["value"] for kpi in results["summary"]["segments"][0]["kpis"]}
    assert kpis["total_sales"] == "60.67"  # 3 x 19.99 + 7 x 0.10, exactly; the row with no quantity is left out
    assert kpis["gross_profit"] == "14.88"  # 60.67 - (3 x 15.10 + 7 x 0.07)
    assert any("calculated as Qty x Unit Price" in assumption for assumption in results["summary"]["assumptions"])
    assert "1 row with no sales value was left out" in job["headline"]


def test_ambiguous_dates_are_read_day_first_and_the_assumption_is_reported(account):
    content = b"Date,Product,Sales Amount\n01/09/2026,Sugar,10.00\n02/09/2026,Rice,20.00\n03/10/2026,Salt,5.00\n"
    upload = account.upload(content)
    job = account.analyse(upload["dataset_version_id"], "Analyse sales by month")
    results = account.get(f"/analysis-jobs/{job['id']}/results").json()
    monthly = next(t for t in results["summary"]["segments"][0]["tables"] if t["key"] == "sales_by_month")
    assert [(row["month"], row["sales"]) for row in monthly["rows"]] == [("2026-09", "30.00"), ("2026-10", "5.00")]
    assumption = "3 dates in 'Date' (such as 01/09/2026) could be read either way. They were read as day/month/year"
    assert any(assumption in note for note in results["summary"]["warnings"] + results["summary"]["assumptions"])


def test_a_request_the_data_only_partly_supports_is_marked_partially_completed(account):
    content = b"Date,Product,Sales Amount\n05/01/2026,Sugar,10.00\n06/02/2026,Rice,20.00\n"
    job = account.analyse(account.upload(content)["dataset_version_id"], PROMPT)
    summary = account.get(f"/analysis-jobs/{job['id']}/results").json()["summary"]
    assert job["status"] == "partially_completed" and "no cost column" in summary["unmet_requests"][0]
    assert "USD 30.00" in job["headline"] and len(account.get("/reports").json()) == 3  # what could be done, was


def test_a_request_the_data_cannot_support_at_all_fails_with_guidance(account):
    content = b"Name,Town\nChipo,Harare\nTendai,Gweru\nRudo,Mutare\n"
    job = account.analyse(account.upload(content)["dataset_version_id"], "Which products are most profitable?")
    assert job["status"] == "failed"
    assert "sales amount column" in job["error_message"] and "'Name'" in job["error_message"]


def test_general_statistics_work_on_data_with_no_recognised_business_columns(account):
    rows = "".join(f"{20 + i},{150 + 2 * i + (i % 3)},{50 + i + (i % 4)}\n" for i in range(30))
    job = account.analyse(account.upload(f"Age,Height,Weight\n{rows}".encode())["dataset_version_id"],
                          "Describe the data, show correlations and what predicts Weight")  # fmt: skip
    results = account.get(f"/analysis-jobs/{job['id']}/results").json()
    assert job["status"] == "completed", job
    keys = {finding["key"] for finding in results["findings"]}
    assert {"descriptive.Age", "correlation.strongest", "regression.model"} <= keys
    regression = next(f for f in results["findings"] if f["key"] == "regression.model")
    assert regression["evidence"]["values"]["target"] == "Weight" and regression["evidence"]["rows_used"] == 30


def test_customer_text_cannot_become_a_formula_or_markup_in_reports(account):
    content = (b'Date,Product,Sales Amount\n05/01/2026,"=HYPERLINK(""http://evil.example"",""click"")",10.00\n'
               b"06/01/2026,<script>alert(1)</script>,20.00\n07/01/2026,<b>bold</b> & co,5.00\n")  # fmt: skip
    job = account.analyse(account.upload(content)["dataset_version_id"], "Analyse sales by product")
    files = {}
    for report in account.get(f"/analysis-jobs/{job['id']}/results").json()["reports"]:
        files[report["format"]] = account.client.get(
            account.get(f"/reports/{report['id']}/download").json()["url"]
        ).content
    html = files["html"].decode()
    assert "<script>alert" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    sheet = load_workbook(io.BytesIO(files["xlsx"]))["Sales by Product"]
    cells = {cell.value: cell for row in sheet.iter_rows(min_row=2) for cell in row[:1] if cell.value}
    injected = next(cell for value, cell in cells.items() if str(value).startswith("=HYPERLINK"))
    assert injected.data_type == "s"  # stored as text, not as a live formula
    assert files["pdf"].startswith(b"%PDF")  # markup in a product name did not break the PDF build


def test_results_that_fail_verification_are_recomputed_once_and_never_published_if_still_wrong(
    account, small_csv, monkeypatch
):
    import app.analytics.verification as verification

    genuine, calls = verification.verify_results, []

    def first_fails(*args, **kwargs):
        calls.append(1)
        outcome = genuine(*args, **kwargs)
        return (
            outcome
            if len(calls) > 1
            else {"passed": False, "checks": [{"name": "Injected failure", "passed": False, "detail": "test"}]}
        )

    version = account.upload(small_csv)["dataset_version_id"]
    monkeypatch.setattr(verification, "verify_results", first_fails)
    job = account.analyse(version, PROMPT)
    tasks = account.get(f"/analysis-jobs/{job['id']}/agents").json()["tasks"]
    assert job["status"] == "completed" and (tasks[3]["attempts"], tasks[4]["attempts"]) == (2, 2)

    monkeypatch.setattr(verification, "verify_results", lambda *a, **k: {
        "passed": False, "checks": [{"name": "Monthly sales add up to total sales", "passed": False, "detail": "off by 0.01"}]})  # fmt: skip
    job = account.analyse(version, PROMPT + " again")
    results = account.get(f"/analysis-jobs/{job['id']}/results").json()
    assert job["status"] == "failed" and "did not pass verification" in job["error_message"]
    assert results["findings"] == [] and results["reports"] == [] and results["summary"] is None
