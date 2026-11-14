"""Organisation-level agent learning profile."""

from __future__ import annotations

from fastapi import APIRouter

from ...schemas.learning import LearningProfileIn, LearningProfileOut, LessonIn
from ...services import learning
from ..deps import Db, Tenant

router = APIRouter(prefix="/organisations/learning-profile", tags=["learning"])


@router.get("", response_model=LearningProfileOut)
def get_profile(ctx: Tenant, db: Db) -> LearningProfileOut:
    return learning.get(db, ctx)


@router.put("", response_model=LearningProfileOut)
def save_profile(body: LearningProfileIn, ctx: Tenant, db: Db) -> LearningProfileOut:
    return learning.save(db, ctx, body)


@router.post("/lessons", response_model=LearningProfileOut)
def add_lesson(body: LessonIn, ctx: Tenant, db: Db) -> LearningProfileOut:
    return learning.add_lesson(db, ctx, body.lesson, source=body.source)
