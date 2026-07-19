"""AI advisor (BYO key) — config + generation.

GET  /api/advisor/config            -> provider/model/base_url + {key_set: bool}
PUT  /api/advisor/config            -> write config; api_key is write-only
POST /api/advisor/generate?owner=   -> build anonymized summary + call the model
GET  /api/advisor/latest?owner=     -> most recent suggestion

The API key is never returned. Generation is user-triggered only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.db.models import AiConfig, AiSuggestion
from app.services import advisor

router = APIRouter(tags=["advisor"])


class ConfigBody(BaseModel):
    provider: str  # anthropic | openai_compat
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None  # write-only; omitted leaves the stored key intact


@router.get("/advisor/config")
async def get_config(db: AsyncSession = Depends(get_session)) -> dict:
    row = await db.get(AiConfig, 1)
    if row is None:
        return {"provider": None, "model": None, "base_url": None, "key_set": False}
    return {
        "provider": row.provider,
        "model": row.model,
        "base_url": row.base_url,
        "key_set": row.api_key_encrypted is not None,
    }


@router.put("/advisor/config")
async def put_config(body: ConfigBody, db: AsyncSession = Depends(get_session)) -> dict:
    if body.provider not in ("anthropic", "openai_compat"):
        raise HTTPException(status_code=400, detail="Unknown provider.")
    row = await db.get(AiConfig, 1)
    if row is None:
        row = AiConfig(id=1)
        db.add(row)
    row.provider = body.provider
    row.model = body.model
    row.base_url = body.base_url
    if body.api_key:  # only overwrite when a new key is supplied
        row.api_key_encrypted = advisor.encrypt_key(body.api_key)
    await db.commit()
    return {"status": "ok", "key_set": row.api_key_encrypted is not None}


@router.post("/advisor/generate")
async def generate(
    owner: str = Query("all"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    row = await db.get(AiConfig, 1)
    if row is None or row.api_key_encrypted is None or not row.provider:
        raise HTTPException(status_code=400, detail="Configure the AI provider + API key first.")
    api_key = advisor.decrypt_key(row.api_key_encrypted)
    if api_key is None:
        raise HTTPException(status_code=400, detail="Stored key could not be read — re-enter it.")

    summary = await advisor.build_summary(db, owner)
    try:
        content = await advisor.generate(row.provider, api_key, row.base_url, row.model, summary)
    except Exception as exc:  # noqa: BLE001 — surface provider errors to the user
        raise HTTPException(status_code=502, detail=f"Generation failed: {exc}") from exc

    suggestion = AiSuggestion(
        owner=owner, provider=row.provider, model=row.model,
        content=content, input_summary=summary,
    )
    db.add(suggestion)
    await db.commit()
    await db.refresh(suggestion)
    return {
        "id": suggestion.id,
        "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
        "content": content,
    }


@router.get("/advisor/latest")
async def latest(
    owner: str = Query("all"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    rows = await db.execute(
        select(AiSuggestion)
        .where(AiSuggestion.owner == owner)
        .order_by(desc(AiSuggestion.created_at))
        .limit(1)
    )
    s = rows.scalar_one_or_none()
    if s is None:
        return {}
    return {
        "id": s.id,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "content": s.content,
        "model": s.model,
    }
