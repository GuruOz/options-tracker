"""Home-dashboard widget layout persistence, one saved layout per scope.

GET /api/dashboard/layout?scope=all  -> {"layout": <json> | null}
PUT /api/dashboard/layout?scope=all  -> upsert the layout JSON

The layout shape is owned by the frontend (widget grid items); the backend just
stores and returns the blob.
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_session
from app.db.models import DashboardLayout

router = APIRouter(tags=["dashboard"])


class LayoutBody(BaseModel):
    layout: dict


@router.get("/dashboard/layout")
async def get_layout(
    scope: str = Query("all"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    row = await db.get(DashboardLayout, scope)
    return {"scope": scope, "layout": row.layout if row else None}


@router.put("/dashboard/layout")
async def put_layout(
    body: LayoutBody,
    scope: str = Query("all"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    stmt = (
        pg_insert(DashboardLayout)
        .values(scope=scope, layout=body.layout)
        .on_conflict_do_update(
            index_elements=["scope"], set_={"layout": body.layout}
        )
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}
