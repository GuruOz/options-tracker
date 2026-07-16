"""IBKR Flex Web Service client — standalone HTTP API for historical trade data.

Does NOT use the CP Gateway. Calls IBKR's servers directly with a long-lived
token and pre-configured query ID.

Setup (one-time, in IBKR Account Management):
  1. Settings -> Flex Web Service -> Enable, generate a token
  2. Reports -> Flex Queries -> Create Activity Flex Query
     - Include: Trade Confirms, Orders
     - Date period: Since Inception (or custom wide range)
     - Format: XML
     - Note the Query ID
  3. Set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in .env
"""
from __future__ import annotations

import asyncio
import time

import defusedxml.ElementTree as ET
import defusedxml.common
import httpx

from app.core.logging import get_logger

log = get_logger("ibkr.flex_web")

FLEX_BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"


async def fetch_flex_trades(
    token: str,
    query_id: str,
    *,
    max_retries: int = 3,
    poll_retries: int = 30,
    initial_delay: float = 5.0,
) -> list[dict]:
    """Fetch all trades via Flex Web Service. Returns trade dicts for upsert.

    Two-step protocol:
      1. SendRequest -> get a reference code
      2. Poll GetStatement with reference until XML is ready
    """
    t = int(time.time() * 1000)
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(max_retries):
            ref_resp = await client.get(
                f"{FLEX_BASE}/SendRequest",
                params={"t": token, "q": query_id, "v": "3", "_": str(t)},
            )
            ref_resp.raise_for_status()
            ref_text = ref_resp.text

            ref_code = _parse_reference(ref_text)
            if not ref_code:
                log.warning("flex_no_reference", attempt=attempt, response=ref_text[:200])
                return []

            await asyncio.sleep(initial_delay)

            for _ in range(poll_retries):
                stmt_resp = await client.get(
                    f"{FLEX_BASE}/GetStatement",
                    params={"t": token, "q": ref_code, "v": "3"},
                )
                stmt_resp.raise_for_status()
                stmt_text = stmt_resp.text

                if "<FlexQueryResponse" in stmt_text and "<FlexStatements" in stmt_text:
                    from app.clients.ibkr.flex_parse import parse_flex_xml
                    trades = parse_flex_xml(stmt_text, "")
                    log.info("flex_fetch_success", trades=len(trades))
                    return trades

                if "statement generation in progress" in stmt_text.lower():
                    await asyncio.sleep(2)
                    continue

                if "no statements available" in stmt_text.lower():
                    log.info("flex_no_statements")
                    return []

                err = _parse_error(stmt_text)
                if err:
                    log.warning("flex_statement_error", error=err)
                else:
                    log.warning("flex_statement_unrecognized", body=stmt_text[:500])
                await asyncio.sleep(2)

            log.warning("flex_statement_timeout", ref_code=ref_code)
            # fall through to outer retry loop — SendRequest again for a fresh attempt

        log.error("flex_sendrequest_exhausted")
        return []


def _parse_reference(xml_text: str) -> str | None:
    """Extract ReferenceCode from SendRequest response XML."""
    try:
        root = ET.fromstring(xml_text)
        code = root.findtext("ReferenceCode")
        if code:
            return code
        url_el = root.find("Url")
        if url_el is not None and url_el.text:
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(url_el.text).query)
            refs = qs.get("q", [])
            if refs:
                return refs[0]
    except (ET.ParseError, defusedxml.common.DefusedXmlException):
        pass
    return None


def _parse_error(xml_text: str) -> str | None:
    """Extract error message from Flex response XML."""
    try:
        root = ET.fromstring(xml_text)
        err = root.findtext("ErrorMessage")
        if err:
            return err
        status = root.findtext("Status")
        if status and status.lower() != "success":
            return status
    except (ET.ParseError, defusedxml.common.DefusedXmlException):
        if "error" in xml_text.lower():
            return xml_text[:200]
    return None
