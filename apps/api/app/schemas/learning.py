"""Request and response shapes for the organisation learning profile."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ReportStyle = Literal["executive", "balanced", "detailed"]


class LearningProfileIn(BaseModel):
    business_context: str = Field(default="", max_length=2000)
    glossary: str = Field(default="", max_length=3000)
    analysis_preferences: str = Field(default="", max_length=2000)
    report_style: ReportStyle = "executive"

    @field_validator("business_context", "glossary", "analysis_preferences")
    @classmethod
    def _tidy(cls, value: str) -> str:
        return "\n".join(line.rstrip() for line in value.strip().splitlines())


class LearningProfileOut(LearningProfileIn):
    lessons: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class LessonIn(BaseModel):
    lesson: str = Field(min_length=1, max_length=500)
    source: str | None = Field(default=None, max_length=120)

    @field_validator("lesson")
    @classmethod
    def _tidy(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Write a short lesson for the agents.")
        return cleaned


class JobFeedbackIn(BaseModel):
    rating: Literal["helpful", "not_helpful"]
    lesson: str | None = Field(default=None, max_length=500)

    @field_validator("lesson")
    @classmethod
    def _tidy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None
