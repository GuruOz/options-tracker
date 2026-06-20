# Roll-chain redesign — design doc

Status: **planned, not yet implemented.** Written 2026-06-21 after a working
session. Points 1 & 2 below are **done and committed** (branch
`feat/roll-chain-redesign`); everything under "Point 3" is the spec to build
later.

## How to resume (read this first)

You are picking up a feature mid-stream. **This file is the single source of
truth** — the user should not have to re-explain anything.

1. Read this whole doc. The product context, the user's decisions, the data
   model, the algorithm, and the build order are all here.
2. Points 1 & 2 (closed-chain label `NVDA 216P` + column trim) are **already
   shipped** — see "Already done this session" and the named files. Don't redo
   them.
3. The remaining work is **Point 3** (redefine how a chain is formed). Start at
   "Suggested build order".
4. **Three open questions** are listed at the very bottom. They have recommended
   defaults. Confirm them with the user in one short message *before* writing
   the migration, then proceed. Don't block on anything else.
5. Conventions: backend = FastAPI + SQLAlchemy async + Alembic (latest revision
   `0004_roll_chain_unique.py`); chain logic is a pure function in
   `backend/app/analytics/rolls.py` covered by `backend/tests/test_rolls.py`;
   frontend = React + TanStack Query + Tailwind. Verify with
   `cd frontend && npx tsc --noEmit` and `cd backend && python -m pytest`.

---

## Context: what this app is for

Track an income-seller's option trades and earnings. The user sells options
(mostly short puts/calls), **rolls the same strike indefinitely** (buy-to-close
+ re-sell, *or* let it expire worthless and sell the next one), and considers a
single "trade" to stay open — possibly for **several months** — until they
either buy it back for good, let it expire and stop, or intentionally close
early. A chain = one such continuous trade. The closed-chains table is the
earnings ledger.

---

## Already done this session (Points 1 & 2) ✅

1. **Closed chains show `NVDA 216P`, not the raw `NVDA 260618P00216000`.**
   - `backend/app/db/repo.py` → `roll_chain_summaries()` now joins each leg to
     its `Execution`, picks the opening leg, derives a clean ticker
     (`_underlying_ticker()` = first whitespace token) + `strike`, and returns a
     `strike` field.
   - `frontend/src/api/types.ts` → `RollChain` gained `strike: number | null`.
   - `frontend/src/components/PositionsPanel.tsx` → `chainLabel()` renders
     `underlying + strike + right`.
2. **Removed the `Chain` (chain_id) and `Right` columns** from the closed-chains
   table in `PositionsPanel.tsx`.

Verified: `npx tsc --noEmit` clean; `pytest tests/test_rolls.py` green (the pure
function in `analytics/rolls.py` was untouched).

---

## Point 3: redefine how a chain is formed

### Current definition (the problem)

`backend/app/analytics/rolls.py` keys chains by **`conid`** (one option
contract) and links contracts into a chain only via a **roll**: a buy-to-close
*immediately* followed by a sell-to-open on the same underlying + right, **within
5 minutes**. This fails the user's workflow:

- **Expiry is invisible.** Letting an option expire worthless produces **no
  closing trade** in IBKR's Trades feed. So the chain stays `open` forever, and
  the next week's sell — with no buy-to-close in front of it — starts a *new*
  chain. Expiry-then-resell sequences fragment into many one-leg open chains.
- **5-minute window too tight.** Rolls done as two separate orders, or apart in
  time, don't link.

### Decisions made by the user (2026-06-21)

- **Grouping = same strike only.** A chain is the continuous lifecycle of short
  positions on the same `(account, underlying, right, strike)`. Re-selling the
  same strike after the prior leg closed/expired **continues** the chain.
- **Manual cross-strike roll.** Rarely the user rolls to a *different* strike for
  operational ease. Don't auto-merge across strikes — instead let them
  **manually attach** an execution/leg (or merge another chain) into an existing
  chain.
- **Expiry & early close need manual override.** The user sometimes closes early
  in a way IBKR's Trades feed *does* capture, but also wants to be able to
  **manually mark a chain closed** (date + reason) when automation can't tell.

### Can IBKR tell us an option expired worthless? — yes, conditionally

- **Trades feed alone: no.** A worthless expiry generates no `<Trade>`. The
  current importer (`flex_parse.py`, `csv_import.py`) only reads `<Trades>` /
  trade rows, so expiry is currently undetectable.
- **Flex Query with the "Option Exercises, Assignments and Expirations" section
  enabled: yes.** That section emits `OptionEAE` records (expiration /
  assignment / exercise) with the contract and quantity. Expiration =
  worthless; assignment = the option closed + a matching stock trade appears.
  Individual `<Trade>` rows also carry a `notes`/`code` attribute (`Ep`=expired,
  `A`=assigned, `Ex`=exercised, `O`/`C`=open/close) that can corroborate.
- **Inference fallback** (when EAE isn't in the export): a short leg whose
  `expiry < today` with no closing trade → assume **expired worthless** and set
  the close at the expiry date with zero closing cost (keep full premium). If a
  spot/settlement price near expiry is available and the option was ITM, flag as
  **assigned** instead; otherwise default to expired and let the user correct.

---

## Proposed implementation

### 1. Data model

Chains become **strike-scoped** and must carry **manual overrides** that survive
the rebuild job (today the builder regenerates purely from executions — manual
edits would be clobbered).

- `roll_chains`: add `strike (Numeric)`. Chain identity = `(account_id,
  underlying_symbol, right, strike)` for the auto-builder. Add
  `close_reason (String)` — one of `bought_back | expired | assigned |
  manual_close`. Add `is_manual (Boolean)` / or a `manual_locked` flag so the
  builder won't reopen/reclose a chain the user has manually finalized.
- `roll_chain_legs`: `role` already supports `open/close/roll/assignment`; add
  `expired` and allow a leg with **no `exec_id`** (synthetic expiry/manual
  close — needs the FK to be nullable, which it already is).
- New table **`chain_adjustments`** (durable user intent the builder must honor):
  - `manual_link`: force `exec_id` (or whole chain) X into chain Y (cross-strike
    roll).
  - `manual_close`: close chain Y at date D with reason R.
  - `manual_split`: detach a leg into its own chain.
  The builder reads these and applies them after the automatic pass, and never
  overwrites a chain/leg covered by an adjustment.

Migration: new Alembic revision (follows `0004_roll_chain_unique.py`). Backfill
`strike` on existing chains from the opening leg's execution.

### 2. Algorithm (`analytics/rolls.py` rewrite)

Group executions by `(underlying, right, strike)`, process chronologically:

- **SELL**: if an open chain exists for the key → continue it (open leg). Else
  start a new chain at that strike.
- **BUY (buy-to-close)**: reduce the open position on the key. When the position
  returns to flat, the chain becomes **closeable** but stays "continuable":
  - if the next same-key SELL arrives within a **continuation window** (default:
    on/before the leg's expiry cycle, or N days — make it a setting), it
    continues the same chain;
  - otherwise the chain closes (`bought_back`) at the buy-to-close time.
- **EXPIRY** (from OptionEAE, or inferred): if the position is short at expiry
  with no buy-to-close → synthesize an `expired` close leg at the expiry date,
  zero cost. Same continuation-window rule applies for the next same-key sell.
- **Manual adjustments** applied last; builder treats manually-finalized chains
  as immutable.

Open design question to confirm before coding: the **continuation window**.
Pure same-strike grouping with no window would merge two unrelated campaigns at
the same strike months apart. Recommended default: continue iff the next sell is
the same strike *and* lands within the prior leg's expiry month (or a
configurable `CHAIN_CONTINUATION_DAYS`). Confirm with user.

### 3. Importer changes

- Extend the **Flex** query + `flex_parse.py` to parse the `OptionEAE` section
  (and/or trade `notes`/`code`) so expiry/assignment are captured directly.
  Document enabling that section in the Flex Query in the README/import help.
- Keep the inference fallback for CSV/legacy exports.

### 4. API

- `GET /api/chains` already returns `strike`; add `close_reason`,
  per-leg detail (date, role, strike, price, credit) for an expandable row.
- New endpoints for manual ops:
  - `POST /api/chains/{chain_id}/close` `{date, reason}` → manual_close.
  - `POST /api/chains/{chain_id}/legs` `{exec_id}` → manual_link (cross-strike
    roll) / merge.
  - `POST /api/chains/{chain_id}/split` `{leg_id}`.
  Each writes a `chain_adjustments` row and re-runs the builder.

### 5. Frontend (`PositionsPanel.tsx`)

- Closed-chains rows become **expandable** to show legs (date, action, strike,
  credit) so the user can audit a chain's history. Show `close_reason` as a
  small pill (Expired / Bought back / Assigned / Closed manually).
- Row actions: **Close manually** (date + reason), **Add roll** (attach an
  execution — for the cross-strike case), **Split**.
- Keep the `NVDA 216P` label; for a manually cross-strike-merged chain, show the
  strike range (e.g. `NVDA 216→210P`).

### 6. Tests

- Extend `tests/test_rolls.py`: same-strike continuation across an expiry (no
  buy-to-close); same-strike re-sell after a gap beyond the continuation window
  = new chain; cross-strike NOT auto-merged; manual link merges; manual close
  honored and not clobbered by a rebuild; expired leg synthesis & credit math.
- Importer tests for OptionEAE parsing.

---

## Suggested build order

1. Migration: add `strike`, `close_reason`, manual flags; `chain_adjustments`
   table; backfill `strike`.
2. Rewrite `analytics/rolls.py` to strike-scoped grouping + expiry synthesis +
   continuation window. Update tests.
3. Wire `build_rolls` job to read `chain_adjustments` and preserve manual edits.
4. Flex importer: parse OptionEAE (+ inference fallback).
5. API endpoints for manual close / link / split.
6. Frontend: expandable legs, close-reason pills, manual actions.

## Open questions to confirm before coding

- Continuation window length / rule (see Algorithm note).
- Cross-strike merged-chain label format (`216→210P`?).
- Whether to attempt auto-assignment detection (needs settlement price) or
  always default expiry→worthless and rely on manual correction.
