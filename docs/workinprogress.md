# Options Tracker — Work in Progress

Features implemented halfway, known issues, and items that need attention before
the next release.

---

## IBEAM authentication instability

**Status:** Resolved for now (2026-06-20), but fragile.

**Background:** IBKR periodically updates their login page HTML, breaking IBEAM's
hardcoded CSS selectors. The login flow broke in June 2026 for live accounts.

**Current working config:**
- `IBEAM_AUTHENTICATION_STRATEGY=A` — older strategy that found the form
- `IBEAM_MANUAL_TWO_FA=true` — skips browser DOM hunting for 2FA elements; polls gateway auth status instead
- `IBEAM_TWO_FA_INPUT_EL_ID=ID@@xyz-field-silver-response` — IBKR renamed from `bronze` in 2026
- `IBEAM_USER_NAME_EL=NAME@@user_name`
- `IBEAM_SUBMIT_EL=CSS_SELECTOR@@button[type="submit"]`
- `IBEAM_OAUTH_TIMEOUT=60`

**Risk:** IBKR may change the login page again. If login breaks after this date:
1. Check `gateway/outputs/` for failure screenshots (mounted volume)
2. Inspect the login page HTML to find current element IDs/names
3. Update the selectors in `docker-compose.yml` under `ibkr-gateway` environment
4. See [IBEAM Configuration wiki](https://github.com/Voyz/ibeam/wiki/IBeam-Configuration) for selector syntax

**Login reliability fixes (2026-06-20):**
- **Re-triggering 2FA now works.** Login *restarts* the IBEAM container instead of
  calling `start()` (a no-op on an already-running container). IBEAM gives up after
  one failed auth (`RESTART_FAILED_SESSIONS=false`, `MAX_FAILED_AUTH=1`), so without
  a restart a missed push left the gateway idle with no way to request another.
  Clicking "Pull Fresh Data" again now always sends a new push.
- **Late approvals are no longer auto-logged-out.** Previously, approving 2FA after
  the login request timed out left an authenticated gateway with `user_logged_in=False`,
  which the passive monitor released within 45 s. The monitor now *adopts* such a
  session (detect account + pull) when a login was requested in the last 5 min
  (`_recent_login_intent`, `_LOGIN_ADOPT_WINDOW_SECONDS`).
- **Timeout raised** from 45 s to 120 s (`PULL_LOGIN_TIMEOUT_SECONDS`) so the
  synchronous request doesn't expire before IBEAM finishes starting.

**Still fragile / possible follow-ups:**
- The 5-min adopt window is a heuristic; a genuine stray session that authenticates
  within 5 min of a (failed) login click would be adopted rather than released.
- No automatic retry if IBEAM itself crashes mid-login — the user must click again.

---

## Flex Web Service — one-time setup required

**Status:** Implemented and working, but requires manual setup.

The `import_flex_trades` job calls IBKR's Flex Web Service directly. For this
to work, the user must:

1. Log into IBKR Client Portal → Settings → Flex Web Service → Enable → Generate token
2. Reports → Flex Queries → Create Activity Flex Query:
   - Sections: Trades + Option Exercises, Assignments and Expirations
   - Format: XML
   - Period: Since Inception
   - Breakout by Day: No
3. Copy the token to `IBKR_FLEX_TOKEN=` in `.env`
4. Copy the query ID (from the URL after saving) to `IBKR_FLEX_QUERY_ID=` in `.env`

Without these env vars set, the job silently returns (no error). The CSV upload
(`POST /api/trades/upload`) remains available as a manual alternative.

---

## CSV upload parser — IBKR format sensitivity

**Status:** Implemented but untested against all CSV variants.

The `csv_import.py` parser handles the standard IBKR Activity Statement CSV format.
IBKR may change column headers or date formats between reports. Known limitations:
- Option symbol parsing assumes `"UNDERLYING DDMMMYY STRIKE P/C"` format
- `exec_id` is synthesized from date+symbol+side+index (not IBKR's native exec ID)
- Date formats tried: `YYYY-MM-DD, HH:MM:SS`, `YYYYMMDD;HHMMSS`
- Buy/sell direction comes from the `Buy/Sell` column or the **sign of `Quantity`**
  (negative = sell); the `Code` column holds trade codes (O/C/A/Ex/…), not B/S, so it
  is not used for direction. `qty` is stored unsigned (direction lives in `side`).

If the CSV import fails, check the column headers in the downloaded file against
the parser's expected keys.

---

## Roll-chain detection — edge cases

**Status:** Implemented and unit-tested (`backend/tests/test_rolls.py`).

**What works:** SELL→open chain, BUY→close chain, roll (BUY+SELL within 5 min)→same chain.
Cross-batch chains correctly closed (and rolls continued) via existing open chain
seeding from DB.

**Fixed (2026-06-20):** roll detection used to fragment every roll into separate
chains, mark the original chain `closed`, and double-count the buy-to-close leg. The
SELL look-back ran after the BUY branch had already popped/closed the chain, so the
roll could never find it. Detection now happens at the **BUY with a one-step
look-ahead**: a buy-to-close immediately followed by a matching SELL continues the
same open chain, counting the buy once. See `analytics/rolls.py` and the regression
tests.

**Edge cases not handled:**
- **Roll split across batches:** only the within-batch roll is linked. If the
  buy-to-close and the sell-to-open land in *different* polling batches, the BUY
  closes the chain and the SELL opens a fresh one (no roll linkage). The common
  full-history import (flex/CSV) processes everything in one batch, so it is
  unaffected; live polling occasionally is.
- **Assignment/expiration:** Currently creates an orphan chain if a position is
  closed by assignment. No execution appears in the trade feed for assignments.
  Would need to detect position disappearance from one poll to the next.
- **Partial closes:** If you sell 2 contracts and buy back 1, the logic treats
  the buy as closing the entire chain. Chain should stay open with adjusted quantity.
- **Multi-leg rolls:** Rolling multiple contracts at once (e.g., sell 5, buy 5)
  should work if the executions come as consecutive BUY+SELL pairs within 5 min.

**Open items:**
- [ ] Handle roll legs that span separate polling batches
- [ ] Handle assignment/expiration closures (no trade execution exists)
- [ ] Handle partial closes (buy qty < open qty)
- [x] Add unit tests for `analytics/rolls.py` — `backend/tests/test_rolls.py` (7 cases)

---

## MarketPanel removed — VIX chart pending

The MarketPanel component was removed per user request. The spec panel 6 calls
for a market context chart. `echarts` and `lightweight-charts` are in
`package.json` but not used anywhere. When re-implementing, build a standalone
market chart component (not the old table-based MarketPanel).

---

## `flex_parse.py` — unused XML parser

The file `backend/app/clients/ibkr/flex_parse.py` was written for the original
(abandoned) CP Gateway flex query approach. It handles the XML format from
IBKR's Flex Web Service and IS used by `flex_web.py`. **Do not delete** — it
is actively imported by `flex_web.py:fetch_flex_trades()`.

---

## Docker socket mount — security note

The backend mounts `/var/run/docker.sock` to start/stop the IBEAM container.
This gives the backend control over Docker. For a self-hosted single-user app
this is acceptable, but options to harden:
- Use a Docker socket proxy (e.g., `tecnativa/docker-socket-proxy`) that limits
  access to only `POST /containers/{name}/start` and `POST /containers/{name}/stop`
- Or use `docker compose` subprocess calls instead of direct socket access

---

## Pending code cleanup

- [ ] Remove unused `flex_request()`, `flex_status()`, `flex_download()` from `client.py` if they weren't already removed (check current state)
- [ ] Remove `SessionBanner.tsx` — dead component, replaced by HeaderBar
- [ ] Remove `AccountPanel.tsx` — dead component, replaced by HeaderBar stats
- [ ] Remove `MarketPanel.tsx` — dead component, removed from App.tsx but file still exists
- [x] Add `rolls.py` unit tests — `backend/tests/test_rolls.py`
- [x] Removed dead `_extract_right/_extract_strike/_extract_expiry`, `_MONTH_MAP`, `import re` from `csv_import.py`
- [x] Removed unused `poll_marketdata_seconds` setting from `core/config.py`
