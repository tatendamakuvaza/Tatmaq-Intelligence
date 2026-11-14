"""Agent learning, executive feedback and the optional Arena AI assistant.

The learning profile is guidance only: these tests check that it is stored per
organisation, that only owners/admins may change it, that it reaches the prompts,
and that it can never alter a calculated figure. The Arena tests script the HTTP
gateway; they do not call the live service.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import psycopg
import pytest
from sqlalchemy import func, select

from app.agents.chief_intelligence.prompts import planner_user_message
from app.agents.report_generation.executive_summary import template_summary
from app.agents.report_generation.report_model import ReportModel
from app.core.config import Settings
from app.core.database import system_session
from app.llm import ArenaClient, LLMResponse, build_llm
from app.models import AuditLog
from app.services.learning import prompt_block
from conftest import add_member, new_account

PROMPT = "Analyse my sales and identify my most profitable products."
PROFILE_PATH = "/organisations/learning-profile"


def put_profile(account, body):
    return account.client.put(f"/v1{PROFILE_PATH}", json=body, headers=account.headers)


def as_member(client, owner, role):
    """A second signed-in user attached to the owner's organisation with ``role``."""
    other = new_account(client, f"{role.title()} colleague")
    add_member(owner.organisation_id, other.user_id, role)
    other.organisation_id, other.workspace_id = owner.organisation_id, owner.workspace_id
    return other


def audit_count(action: str, organisation_id: str) -> int:
    with system_session() as session:
        return session.scalar(
            select(func.count()).select_from(AuditLog).filter_by(action=action, organisation_id=organisation_id)
        )


# --------------------------------------------------------------------------- learning profile


def test_profile_defaults_and_owner_can_teach_the_agents(account):
    default = account.get(PROFILE_PATH)
    assert default.status_code == 200, default.text
    assert default.json() == {
        "business_context": "",
        "glossary": "",
        "analysis_preferences": "",
        "report_style": "executive",
        "lessons": [],
        "updated_at": None,
    }

    saved = put_profile(
        account,
        {
            "business_context": "We wholesale building materials in Zimbabwe.",
            "glossary": "GP = gross profit. HRE = Harare.",
            "analysis_preferences": "Always compare branches.",
            "report_style": "detailed",
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["report_style"] == "detailed" and body["updated_at"]
    assert "wholesale" in body["business_context"]

    lesson = account.post(
        f"{PROFILE_PATH}/lessons", json={"lesson": "  Show amounts in USD.  ", "source": "board meeting"}
    )
    assert lesson.status_code == 200, lesson.text
    assert lesson.json()["lessons"] == ["Show amounts in USD. (source: board meeting)"]

    # Saving the profile again keeps the lessons already learned.
    again = put_profile(account, {"business_context": "Updated context.", "report_style": "executive"})
    assert again.status_code == 200
    assert again.json()["lessons"] == ["Show amounts in USD. (source: board meeting)"]
    assert again.json()["glossary"] == ""  # omitted fields reset to their defaults

    assert audit_count("organisation.learning_profile_updated", account.organisation_id) == 2
    assert audit_count("organisation.learning_lesson_added", account.organisation_id) == 1


def test_lessons_are_capped_and_trimmed(account):
    for index in range(30):
        response = account.post(f"{PROFILE_PATH}/lessons", json={"lesson": f"Lesson {index}"})
        assert response.status_code == 200, response.text
    lessons = account.get(PROFILE_PATH).json()["lessons"]
    assert len(lessons) == 24 and lessons[0] == "Lesson 6" and lessons[-1] == "Lesson 29"
    assert account.post(f"{PROFILE_PATH}/lessons", json={"lesson": "   "}).status_code == 422
    assert account.post(f"{PROFILE_PATH}/lessons", json={"lesson": "x" * 501}).status_code == 422


def test_only_owners_and_admins_may_change_the_profile(client, account):
    analyst = as_member(client, account, "analyst")
    viewer = as_member(client, account, "viewer")
    admin = as_member(client, account, "admin")
    put_profile(account, {"business_context": "Owner's context."})

    for member in (analyst, viewer):
        assert member.get(PROFILE_PATH).status_code == 200  # everyone may read it
        assert member.get(PROFILE_PATH).json()["business_context"] == "Owner's context."
        assert put_profile(member, {"business_context": "hijacked"}).status_code == 403
        assert member.post(f"{PROFILE_PATH}/lessons", json={"lesson": "hijacked"}).status_code == 403
    assert put_profile(admin, {"business_context": "Admin's context."}).status_code == 200
    assert account.get(PROFILE_PATH).json()["business_context"] == "Admin's context."


def test_another_organisation_cannot_see_the_profile(make_account):
    a, b = make_account("Learning A"), make_account("Learning B")
    put_profile(a, {"business_context": "Only A knows this."})
    assert b.get(PROFILE_PATH).json()["business_context"] == ""
    response = a.client.get(f"/v1{PROFILE_PATH}", headers={**a.headers, "X-Organisation-Id": b.organisation_id})
    assert response.status_code == 404


def as_user(connection, user_id):
    connection.execute("SET LOCAL ROLE tatmaq_app_user")
    connection.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": user_id}),))


def test_the_database_itself_guards_the_learning_column(client, account, database_url):
    """Column-level UPDATE grant + an owner/admin UPDATE policy, with no application code involved."""
    analyst = as_member(client, account, "analyst")
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            as_user(connection, account.user_id)
            updated = connection.execute(
                "UPDATE organisations SET learning_profile = %s WHERE id = %s",
                (json.dumps({"report_style": "balanced"}), account.organisation_id),
            )
            assert updated.rowcount == 1
        with connection.transaction():
            as_user(connection, account.user_id)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(
                    "UPDATE organisations SET name = 'renamed' WHERE id = %s", (account.organisation_id,)
                )
        with connection.transaction():
            as_user(connection, analyst.user_id)
            # The policy's USING clause hides the row from a non-admin: nothing is updated.
            refused = connection.execute(
                "UPDATE organisations SET learning_profile = '{}'::jsonb WHERE id = %s", (account.organisation_id,)
            )
            assert refused.rowcount == 0
    assert account.get(PROFILE_PATH).json()["report_style"] == "balanced"


# --------------------------------------------------------------------------- feedback


def test_feedback_is_recorded_and_owners_lessons_are_saved(client, account, small_csv):
    version = account.upload(small_csv)["dataset_version_id"]
    job = account.analyse(version, PROMPT)
    assert job["status"] == "completed", job

    response = account.post(
        f"/analysis-jobs/{job['id']}/feedback", json={"rating": "helpful", "lesson": "Compare branches every time."}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"recorded": True, "lesson_saved": True}
    assert "Compare branches every time." in account.get(PROFILE_PATH).json()["lessons"][0]
    assert audit_count("analysis.feedback", account.organisation_id) == 1

    analyst = as_member(client, account, "analyst")
    before = len(account.get(PROFILE_PATH).json()["lessons"])
    response = analyst.post(
        f"/analysis-jobs/{job['id']}/feedback", json={"rating": "not_helpful", "lesson": "Analysts cannot teach."}
    )
    assert response.status_code == 200 and response.json() == {"recorded": True, "lesson_saved": False}
    assert len(account.get(PROFILE_PATH).json()["lessons"]) == before
    assert audit_count("analysis.feedback", account.organisation_id) == 2
    assert account.post(f"/analysis-jobs/{job['id']}/feedback", json={"rating": "maybe"}).status_code == 422


def test_feedback_cannot_reach_another_organisations_job(make_account, small_csv):
    a, b = make_account("Feedback A"), make_account("Feedback B")
    job = b.analyse(b.upload(small_csv)["dataset_version_id"], PROMPT)
    assert a.post(f"/analysis-jobs/{job['id']}/feedback", json={"rating": "helpful"}).status_code == 404


# --------------------------------------------------------------------------- guidance reaches the prompts


def test_prompt_block_is_empty_until_something_is_taught():
    assert prompt_block(None) == "" and prompt_block({}) == "" and prompt_block({"lessons": []}) == ""
    block = prompt_block({"business_context": "Wholesale.", "report_style": "executive", "lessons": ["Use USD."]})
    assert block.startswith("Organisation learning profile (guidance only")
    assert "Business context: Wholesale." in block and "Report style: executive" in block and "- Use USD." in block

    message = planner_user_message(
        PROMPT,
        "automatic",
        [{"name": "Sales", "kind": "money"}],
        [],
        learning_profile={"glossary": "GP = gross profit"},
    )
    assert "Glossary: GP = gross profit" in message and "guidance only" in message
    assert "Glossary" not in planner_user_message(PROMPT, "automatic", [], [])


def model_with_style(style):
    return ReportModel(
        title="Sales",
        objective="o",
        request="r",
        organisation="Org",
        dataset_name="d",
        dataset_version=1,
        dataset_filename=None,
        dataset_rows=6,
        dataset_sha256="x",
        job_id="j",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        timezone="UTC",
        period=None,
        segments=[{"key": None, "label": "All", "kpis": []}],
        findings=[
            {"kind": "kpi", "importance": 10 - i, "statement": f"Finding {i}.", "segment": None} for i in range(10)
        ],
        evidence=[],
        warnings=[],
        assumptions=[],
        verification={"passed": True, "checks": []},
        learning_profile={"report_style": style} if style else {},
    )


def test_report_style_changes_only_the_length_of_the_summary():
    assert len(template_summary(model_with_style(None))) == 6  # unchanged default
    assert len(template_summary(model_with_style("executive"))) == 4
    assert len(template_summary(model_with_style("balanced"))) == 6
    assert len(template_summary(model_with_style("detailed"))) == 8
    assert template_summary(model_with_style("executive"))[0] == "Finding 0."


# --------------------------------------------------------------------------- Arena AI client


def test_arena_client_speaks_openai_compatible_without_response_format():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(
            200,
            json={
                "model": "arena-model",
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
                "choices": [{"message": {"content": '```json\n{"answer": "Focus on Harare.", "caveats": []}\n```'}}],
            },
        )

    client = ArenaClient(
        api_key="arena-key",
        model="coding-router-preview",
        base_url="https://api.arena.ai",
        transport=httpx.MockTransport(handler),
    )
    response = asyncio.run(client.complete_json(system="s", user="u"))
    request = seen["request"]
    assert str(request.url) == "https://api.arena.ai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer arena-key"
    payload = json.loads(request.content)
    assert payload["model"] == "coding-router-preview" and "response_format" not in payload
    assert payload["messages"][0] == {"role": "system", "content": "s"}
    assert response.data == {"answer": "Focus on Harare.", "caveats": []} and response.model == "arena-model"
    assert (response.tokens_input, response.tokens_output) == (12, 7)
    assert client.provider == "arena"


def test_build_llm_supports_arena():
    settings = Settings(app_env="test", auth_mode="dev", ai_provider="arena", ai_api_key="k", ai_model="m")
    llm = build_llm(settings)
    assert isinstance(llm, ArenaClient) and llm.provider == "arena" and llm.model == "m"


# --------------------------------------------------------------------------- Arena AI assistant endpoint


class FakeLLM:
    provider = "arena"
    model = "fake-arena-model"

    def __init__(self):
        self.calls = []

    async def complete_json(self, *, system, user, max_output_tokens=2000):
        self.calls.append(json.loads(user))
        return LLMResponse(
            data={"answer": "  Focus on the Harare branch.  ", "caveats": ["Based on verified findings."]},
            model=self.model,
            tokens_input=20,
            tokens_output=9,
        )


def test_assistant_needs_configuration(account):
    response = account.post("/arena/ask", json={"question": "What should we do next?"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "ai_not_configured"


def test_assistant_answers_from_verified_findings(account, small_csv, monkeypatch):
    version = account.upload(small_csv)["dataset_version_id"]
    job = account.analyse(version, PROMPT)
    put_profile(account, {"business_context": "Groceries wholesale.", "report_style": "executive"})
    fake = FakeLLM()
    monkeypatch.setattr("app.services.arena.build_llm", lambda settings: fake)

    response = account.post("/arena/ask", json={"question": "What should the board focus on?", "job_id": job["id"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "Focus on the Harare branch." and body["caveats"] == ["Based on verified findings."]
    assert body["provider"] == "arena" and body["model"] == "fake-arena-model" and body["used_job_id"] == job["id"]
    assert (body["tokens_input"], body["tokens_output"]) == (20, 9)

    payload = fake.calls[0]
    assert payload["question"] == "What should the board focus on?"
    assert "Groceries wholesale." in payload["organisation_learning_profile"]
    verified = payload["verified_tatmaq_analysis"]
    assert verified["request"] == PROMPT and verified["findings"], verified
    assert all(finding["statement"] for finding in verified["findings"])
    # Only the verified summary goes to the model: never a preview of raw rows.
    assert "preview" not in verified and len(verified["findings"]) <= 24


def test_assistant_general_question_without_an_analysis(account, monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr("app.services.arena.build_llm", lambda settings: fake)
    response = account.post("/arena/ask", json={"question": "How do we improve gross margin?"})
    assert response.status_code == 200 and response.json()["used_job_id"] is None
    assert fake.calls[0]["verified_tatmaq_analysis"] is None
    assert account.post("/arena/ask", json={"question": "   "}).status_code == 422


def test_assistant_respects_roles_and_tenant_boundaries(client, account, make_account, small_csv, monkeypatch):
    monkeypatch.setattr("app.services.arena.build_llm", lambda settings: FakeLLM())
    job = account.analyse(account.upload(small_csv)["dataset_version_id"], PROMPT)
    viewer = as_member(client, account, "viewer")
    assert viewer.post("/arena/ask", json={"question": "Anything?"}).status_code == 403
    other = make_account("Other org")
    assert (
        other.post("/arena/ask", json={"question": "Tell me about their sales", "job_id": job["id"]}).status_code == 404
    )
