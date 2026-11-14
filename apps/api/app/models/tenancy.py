"""Organisations, the people in them and their workspaces."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_timestamp, uuid_pk


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    default_currency: Mapped[str] = mapped_column(String(3), default="USD")
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Harare")
    date_order: Mapped[str] = mapped_column(String(3), default="DMY")
    created_at: Mapped[created_timestamp]


class Profile(Base):
    __tablename__ = "profiles"

    # Same id as the Supabase Auth user (auth.users.id).
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[created_timestamp]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid_pk]
    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[dict[str, Any]] = mapped_column(default=dict)


class OrganisationMembership(Base):
    __tablename__ = "organisation_memberships"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id"))
    role: Mapped[str] = mapped_column(String(30), ForeignKey("roles.name"), default="analyst")
    status: Mapped[str] = mapped_column(String(30), default="active")
    created_at: Mapped[created_timestamp]


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    name: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profiles.id"))
    created_at: Mapped[created_timestamp]
