"""Request and response shapes for the optional Arena AI assistant."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ArenaAskIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    job_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def _tidy(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Write a question for the assistant.")
        return cleaned


class ArenaAskOut(BaseModel):
    answer: str
    caveats: list[str] = Field(default_factory=list)
    provider: str
    model: str | None = None
    used_job_id: UUID | None = None
    tokens_input: int = 0
    tokens_output: int = 0
