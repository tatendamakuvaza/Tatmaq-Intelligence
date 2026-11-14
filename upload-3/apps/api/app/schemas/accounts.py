"""Request and response shapes for sign-in, profiles, organisations and workspaces."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .common import ApiModel


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class UserOut(ApiModel):
    id: UUID
    email: str | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ProfileIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)

    @field_validator("full_name")
    @classmethod
    def _tidy(cls, value: str | None) -> str | None:
        return " ".join(value.split()) or None if value else None


class ProfileOut(ApiModel):
    id: UUID
    full_name: str | None
    email: str | None


class OrganisationIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)

    @field_validator("name")
    @classmethod
    def _tidy(cls, value: str) -> str:
        return " ".join(value.split())


class OrganisationOut(ApiModel):
    id: UUID
    name: str
    slug: str
    role: str
    permissions: list[str]
    default_currency: str
    timezone: str
    date_order: str


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _tidy(cls, value: str) -> str:
        return " ".join(value.split())


class WorkspaceOut(ApiModel):
    id: UUID
    name: str
    created_at: datetime


class OrganisationCreated(BaseModel):
    organisation: OrganisationOut
    workspace: WorkspaceOut


class MemberOut(BaseModel):
    user_id: UUID
    full_name: str | None
    email: str | None
    role: str
    status: str
