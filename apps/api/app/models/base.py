"""Declarative base and shared column helpers.

The schema itself is owned by the SQL files in ``database/``; these classes map onto
it and never create tables. ``tests/test_schema_matches_models.py`` fails if the two
drift apart.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column

uuid_pk = Annotated[uuid.UUID, mapped_column(Uuid, primary_key=True, default=uuid.uuid4)]
created_timestamp = Annotated[datetime, mapped_column(DateTime(timezone=True), server_default=func.now())]


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}
