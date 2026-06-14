"""Contract search — proxies secdef/search so the UI can look up conids by ticker."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.clients.ibkr import IBKRAuthError, IBKRClient, IBKRError

router = APIRouter(tags=["contracts"])


@router.get("/contracts/search")
async def search_contracts(q: str, request: Request) -> list[dict]:
    if not q or len(q.strip()) < 1:
        return []
    client: IBKRClient = request.app.state.ibkr
    try:
        results = await client.secdef_search(q.strip().upper())
    except IBKRAuthError:
        raise HTTPException(status_code=503, detail="IBKR session not authenticated")
    except IBKRError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if not isinstance(results, list):
        return []

    out = []
    for r in results:
        has_stk = any(
            (s or {}).get("secType") == "STK"
            for s in (r.get("sections") or [])
        )
        if has_stk:
            try:
                out.append({
                    "conid": int(r["conid"]),
                    "symbol": r.get("symbol") or "",
                    "description": r.get("description") or "",
                })
            except (KeyError, ValueError, TypeError):
                continue
    return out
