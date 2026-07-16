"""Contract search — proxies secdef/search so the UI can look up conids by ticker."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.clients.ibkr import IBKRAuthError, IBKRError
from app.core.gateways import any_authenticated_client

router = APIRouter(tags=["contracts"])


@router.get("/contracts/search")
async def search_contracts(q: str) -> list[dict]:
    if not q or len(q.strip()) < 1:
        return []
    # The contract database is the same whoever asks, so any logged-in user's
    # gateway can answer — the searcher needn't be logged in themselves.
    client = any_authenticated_client()
    if client is None:
        raise HTTPException(status_code=503, detail="No IBKR session authenticated")
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
