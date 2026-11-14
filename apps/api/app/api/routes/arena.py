"""Optional Arena AI assistant endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from ...schemas.arena import ArenaAskIn, ArenaAskOut
from ...services import arena
from ..deps import AppSettings, Db, Tenant

router = APIRouter(prefix="/arena", tags=["arena"])


@router.post("/ask", response_model=ArenaAskOut)
async def ask(body: ArenaAskIn, ctx: Tenant, db: Db, settings: AppSettings) -> ArenaAskOut:
    return await arena.ask(db, ctx, settings, body.question, body.job_id)
