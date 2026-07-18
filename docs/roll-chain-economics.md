# Roll-chain economics — how a chain reports its P&L

How the app values an open roll chain, and what each number on the chain-timeline
card means. Grouping (how executions become a chain) is covered in
[roll-chain-redesign.md](roll-chain-redesign.md); this doc is about the money.

The seller's mental model this reflects: a chain is **one continuous trade** on a
single strike, rolled indefinitely, and it is "correct" only once the short
finally expires worthless (or is intentionally closed). Rolls along the way don't
each start a new deal — they buy more time on the same deal.

---

## The three stored numbers

Every chain carries three credit figures, accumulated commission-net in
`backend/app/analytics/rolls.py` and exposed by `roll_chain_summaries()` in
`backend/app/db/repo.py`:

| Field | Meaning |
|-------|---------|
| `cumulative_credit` | Running sum of **every** cash flow in the chain: option sells (+), buys (−), and — after an assignment — shares booked at strike (−) and share sales (+). This is the `Σ` column on each timeline row. |
| `open_credit` | The credit riding on the short leg that is **open right now**. Scales down as the leg is reduced; reaches 0 once the chain is flat. |
| `initial_credit` | The opening sale the current cycle is working toward — the premium the whole roll campaign is trying to keep. |

`banked_credit = cumulative_credit − open_credit` is derived server-side
([repo.py](../backend/app/db/repo.py) `roll_chain_summaries`).

---

## The four headline figures on the card

Computed by `chainHeadline()` in
[frontend/src/components/ChainTimeline.tsx](../frontend/src/components/ChainTimeline.tsx):

| Line | Formula | Reading |
|------|---------|---------|
| **banked to date** (headline) | `cumulative_credit − open_credit` | Realized P&L of everything that has **settled**. Scenario-proof floor: the credit on the still-open leg is excluded because it isn't money in hand until that leg expires or is bought back. |
| **locked in the open leg** | `open_credit` | Premium riding on the current short. A roll only banks the decay on the leg it *replaced*, so this is not yet income. |
| **if it expires worthless** | `cumulative_credit` | Best case: what the chain nets if the open leg goes to zero. Equals `banked + locked`. |
| **gathered beyond the *N* opener** | `cumulative_credit − initial_credit` | Roll-to-the-end view: credit gathered **over the opening sale** the cycle is working toward. Matches the continuous-trade mental model. Hidden until the chain has rolled at least once (`|cumulative − initial| < 0.5`). |

`banked` and `gathered beyond the opener` are two honest views of the same chain:
- **banked to date** answers *"what is locked in no matter what happens next?"*
- **gathered beyond the opener** answers *"if I hold to expiry as intended, what
  did the rolls add on top of my original premium?"*

They reconcile exactly: `banked + open_credit = cumulative_credit`, and
`initial_credit + (gathered beyond opener) = cumulative_credit`.

---

## Worked example — NVDA 216→215P

| Date | Event | Δ | Σ (`cumulative_credit`) |
|------|-------|----|----|
| 3 Jun | Sell 216P (exp 18 Jun) | +694 | 694 |
| 16 Jun | Buy 216P to close | −634 | 60 |
| 16 Jun | Sell 215P (exp 2 Jul) — roll | +865 | 925 |
| 25 Jun | **Assigned** — buy 100 sh @ 215 | −21,500 | −20,575 |
| 29 Jun | Sell 215P (exp 17 Jul) | +2,126 | −18,449 |
| 29 Jun | Sell 100 sh @ 194.25 | +19,424 | 975 |
| 17 Jul | Buy 215P to close | −1,133 | −158 |
| 17 Jul | Sell 215P (exp 7 Aug) — roll | +1,483 | 1,325 |

Card, while the 7 Aug 215P is open:

- **banked to date: −158** — options settled +1,917, share round-trip −2,076.
- **+1,482 locked in the open leg** (`open_credit`).
- **1,325 if it expires worthless** (`cumulative_credit`).
- **+631 gathered beyond the 694 opener** (`1,325 − 694`).

Banked is negative not because the strategy is losing, but because it realizes the
−2,076 share drawdown now while excluding the +1,482 of offsetting intrinsic still
parked in the open put. As NVDA recovers toward 215 and rolls accrue time value,
banked climbs toward the 1,325.

---

## Early assignment is (near-)neutral, not a loss event

When a short put is assigned early, the disciplined continuation is: **sell the
delivered shares and immediately re-sell the same strike at a later expiry.** The
new put carries intrinsic value equal to `strike − spot`, which is exactly the
mark-to-market loss on the shares — so the intrinsic transfers cleanly and the
seller pockets the new leg's *time* value on top. It synthetically reconstructs
the short put; the assignment changed the *form* of an already-existing drawdown,
it did not create a new loss.

From the example, the 25→29 Jun conversion:

- Shares: −21,500 + 19,424 = **−2,076** realized
- New 215P sold at 21.27 = **+2,126**
- Net **+50** ≈ the ~0.52 × 100 of time value on the re-sale

Caveats (why "near-", not exactly, neutral): capital/margin to take the shares,
gap risk while holding them before re-selling, and the extra commission
round-trip. None of these are captured in the credit figures.

**Consequence for the headline numbers:** because banked-to-date realizes the
share loss but excludes the offsetting intrinsic in the open put, it *understates*
a chain that has been through an early assignment. The **gathered beyond the
opener** line is the one that reflects the seller's continuous-trade view of such
a chain.

---

## Where this lives

- Accumulation & cycle bookkeeping: `backend/app/analytics/rolls.py`
  (`_credit`, `open_credit` / `initial_credit` / `cycle_base_credit`).
- Server-side `banked_credit`: `backend/app/db/repo.py` `roll_chain_summaries()`.
- Card headline & the four lines: `frontend/src/components/ChainTimeline.tsx`
  (`chainHeadline`).
- Positions "Captured %" (mark-based, the middle view between banked and
  if-worthless): `frontend/src/components/PositionsPanel.tsx`.
