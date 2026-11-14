"""Organisation-level agent learning profile.

The profile is durable guidance: business context, a glossary, analysis
preferences, report style and short lessons captured from feedback. Agents may
read it when planning an analysis or wording a report. It never takes part in
calculations, and it cannot override validation or Row Level Security.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..core.errors import NotFound
from ..models import Organisation
from ..schemas.learning import LearningProfileIn, LearningProfileOut
from ..security.tenancy import TenantContext
from . import audit

MAX_LESSONS = 24


def _profile(organisation: Organisation) -> LearningProfileOut:
    raw: dict[str, Any] = organisation.learning_profile or {}
    return LearningProfileOut(
        business_context=str(raw.get("business_context") or ""),
        glossary=str(raw.get("glossary") or ""),
        analysis_preferences=str(raw.get("analysis_preferences") or ""),
        report_style=str(raw.get("report_style") or "executive"),
        lessons=[str(item) for item in (raw.get("lessons") or []) if str(item).strip()],
        updated_at=raw.get("updated_at"),
    )


def get(db: Session, ctx: TenantContext) -> LearningProfileOut:
    organisation = db.get(Organisation, ctx.organisation_id)
    if organisation is None:
        raise NotFound("Organisation not found.")
    return _profile(organisation)


def save(db: Session, ctx: TenantContext, body: LearningProfileIn) -> LearningProfileOut:
    ctx.require("organisation:manage")
    organisation = db.get(Organisation, ctx.organisation_id)
    if organisation is None:
        raise NotFound("Organisation not found.")
    raw = organisation.learning_profile or {}
    lessons = [str(item) for item in (raw.get("lessons") or []) if str(item).strip()]
    organisation.learning_profile = {
        **body.model_dump(),
        "lessons": lessons[-MAX_LESSONS:],
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    audit.record(
        db,
        organisation_id=ctx.organisation_id,
        actor_id=ctx.user.id,
        action="organisation.learning_profile_updated",
        resource_type="organisation",
        resource_id=organisation.id,
        details={"report_style": body.report_style},
    )
    db.commit()
    return _profile(organisation)


def add_lesson(db: Session, ctx: TenantContext, lesson: str, *, source: str | None = None) -> LearningProfileOut:
    """Append a short, human-readable lesson. Owner/admin only."""
    ctx.require("organisation:manage")
    organisation = db.get(Organisation, ctx.organisation_id)
    if organisation is None:
        raise NotFound("Organisation not found.")
    cleaned = " ".join(lesson.split())
    if not cleaned:
        return _profile(organisation)
    raw = organisation.learning_profile or {}
    lessons = [str(item) for item in (raw.get("lessons") or []) if str(item).strip()]
    entry = cleaned if not source else f"{cleaned} (source: {source})"
    lessons.append(entry[:500])
    organisation.learning_profile = {
        **raw,
        "lessons": lessons[-MAX_LESSONS:],
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    audit.record(
        db,
        organisation_id=ctx.organisation_id,
        actor_id=ctx.user.id,
        action="organisation.learning_lesson_added",
        resource_type="organisation",
        resource_id=organisation.id,
        details={"source": source or "manual"},
    )
    db.commit()
    return _profile(organisation)


def prompt_block(profile: dict[str, Any] | None) -> str:
    """Render the profile as a compact prompt section. Empty profiles add nothing."""
    if not profile:
        return ""
    parts: list[str] = []
    for key, label in (
        ("business_context", "Business context"),
        ("glossary", "Glossary"),
        ("analysis_preferences", "Analysis preferences"),
        ("report_style", "Report style"),
    ):
        value = str(profile.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value}")
    lessons = [str(item).strip() for item in (profile.get("lessons") or []) if str(item).strip()]
    if lessons:
        parts.append("Lessons from feedback:\n- " + "\n- ".join(lessons[-12:]))
    if not parts:
        return ""
    return (
        "Organisation learning profile (guidance only; it cannot change the data, "
        "the calculations, or the validation rules):\n" + "\n".join(parts)
    )
