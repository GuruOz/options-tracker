"""Parse an Endowus "Statement of Account" PDF into goal balances + holdings.

Pure functions, no DB — same contract as ``cpf_pdf.py``.

Two things are extracted:
  * goal ending balances (the authoritative per-goal value; the household net
    worth sums these, so it never double-counts), from the "All Investment
    Goals" table; and
  * per-fund holdings (fund, asset class, funding source, units, NAV, value,
    allocation %) for the allocation breakdown.

The fund table is repeated across pages (an aggregated copy plus one per goal),
so holdings are de-duplicated by (fund, funding source) — the household total is
taken from goal balances regardless, keeping the money figure correct.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from pypdf import PdfReader

# "01 Jun 2026 to 30 Jun 2026"
_PERIOD_RE = re.compile(r"(\d{2} \w{3} \d{4}) to (\d{2} \w{3} \d{4})")

# "Display Currency: Singapore Dollar (SGD)" / "US Dollar (USD)".
_CCY_RE = re.compile(r"(?:Display|Plan) Currency:.*\(([A-Z]{3})\)")

# Endowus renders SGD as "S$", USD as "US$" (bare "$" as a fallback). Longest
# alternative first so "US$" wins over "S$".
_MSYM = r"(?:US\$|S\$|\$)"

# "CPF OA S$6,714.45 S$500.00 S$0.00 S$47.72 S$7,262.17"  (goal funding-row: 5 amounts)
_GOAL_ROW_RE = re.compile(
    r"^(?P<funding>CPF OA|CPF SA|CASH|SRS) "
    rf"(?:-?{_MSYM}[\d,]+\.\d{{2}} ){{4}}"
    rf"-?{_MSYM}(?P<end>[\d,]+\.\d{{2}})$"
)

# Fund holdings row, anchored on the funding-source token then the numbers:
# "Amundi Index MSCI World Fund Equity Fund CPF OA 23.1259 S$235.35 S$210.8453 S$5,442.68 74.9%"
_HOLDING_RE = re.compile(
    r"^(?P<rest>.+?) "
    r"(?P<funding>CPF OA|CPF SA|CASH|SRS) "
    r"(?P<units>[\d,]+\.?\d*) "
    rf"{_MSYM}(?P<nav>[\d,]+\.\d+) "
    rf"{_MSYM}(?P<avg>[\d,]+\.\d+) "
    rf"{_MSYM}(?P<value>[\d,]+\.\d{{2}}) "
    r"(?P<alloc>[\d.]+)%$"
)

# For inferring currency when no "Display Currency" line is present.
_USD_HINT_RE = re.compile(r"US\$")

# Known asset-class phrases, longest first so "Fixed Income Fund" wins over "Fund".
_ASSET_CLASSES = [
    "Equity Fund", "Bond Fund", "Fixed Income Fund", "Fixed Income",
    "Multi-Asset Fund", "Multi-Asset", "Multi Asset", "Money Market Fund",
    "Money Market", "Real Estate", "Alternatives", "Commodities", "Cash",
]

# Uppercase headings that are NOT goal names.
_GOAL_NAME_RE = re.compile(r"^[A-Z0-9][A-Z0-9 &/()\-]+$")
_NOT_A_GOAL = {
    "STATEMENT PERIOD", "STATEMENT OF ACCOUNT", "DRIVE", "SG", "OVERVIEW",
}


@dataclass
class EndowusBalance:
    as_of: date
    category: str  # goal name
    balance: float
    currency: str


@dataclass
class EndowusHolding:
    as_of: date
    goal_name: str
    fund_name: str
    asset_class: str | None
    funding_source: str
    units: float
    nav: float
    avg_price: float
    market_value: float
    allocation_pct: float
    currency: str


@dataclass
class EndowusParseResult:
    period_start: date | None
    period_end: date | None
    currency: str = "SGD"  # detected display currency (SGD / USD / ...)
    balances: list[EndowusBalance] = field(default_factory=list)
    holdings: list[EndowusHolding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%d %b %Y").date()
    except ValueError:
        return None


def _split_fund_and_class(rest: str) -> tuple[str, str | None]:
    for cls in _ASSET_CLASSES:
        if rest.endswith(" " + cls):
            return rest[: -(len(cls) + 1)].strip(), cls
    return rest.strip(), None


def _lines(content: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(content))
    out: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        out.extend(line.strip() for line in text.splitlines() if line.strip())
    return out


def _looks_like_goal(line: str) -> bool:
    return (
        len(line) > 3
        and "S$" not in line
        and _GOAL_NAME_RE.match(line) is not None
        and line not in _NOT_A_GOAL
        and not line.startswith("PAGE")
    )


def parse_endowus_pdf(content: bytes) -> EndowusParseResult:
    lines = _lines(content)

    period_start = period_end = None
    for line in lines:
        m = _PERIOD_RE.search(line)
        if m:
            period_start = _parse_date(m.group(1))
            period_end = _parse_date(m.group(2))
            break
    as_of = period_end

    # Display currency: prefer the explicit label, else infer from the money
    # symbol (US$ => USD), else default SGD.
    currency = "SGD"
    for line in lines:
        cm = _CCY_RE.search(line)
        if cm:
            currency = cm.group(1)
            break
    else:
        if any(_USD_HINT_RE.search(line) for line in lines):
            currency = "USD"

    result = EndowusParseResult(
        period_start=period_start, period_end=period_end, currency=currency
    )

    # Goal balances: a goal-name line, then either "No activity" or a funding row.
    pending_goal: str | None = None
    seen_goals: set[str] = set()
    for line in lines:
        gm = _GOAL_ROW_RE.match(line)
        if gm and pending_goal and as_of and pending_goal not in seen_goals:
            result.balances.append(
                EndowusBalance(
                    as_of=as_of, category=pending_goal,
                    balance=_num(gm.group("end")), currency=currency,
                )
            )
            seen_goals.add(pending_goal)
            pending_goal = None
            continue
        if _looks_like_goal(line):
            pending_goal = line

    primary_goal = next(iter(seen_goals)) if len(seen_goals) == 1 else "Portfolio"

    # Holdings: de-dupe across the repeated tables by (fund, funding source).
    seen_holdings: set[tuple[str, str]] = set()
    for line in lines:
        hm = _HOLDING_RE.match(line)
        if not hm:
            continue
        fund, asset_class = _split_fund_and_class(hm.group("rest"))
        key = (fund, hm.group("funding"))
        if key in seen_holdings:
            continue
        seen_holdings.add(key)
        if asset_class is None:
            result.warnings.append(f"unknown asset class for: {fund}")
        result.holdings.append(
            EndowusHolding(
                as_of=as_of,
                goal_name=primary_goal,
                fund_name=fund,
                asset_class=asset_class,
                funding_source=hm.group("funding"),
                units=_num(hm.group("units")),
                nav=_num(hm.group("nav")),
                avg_price=_num(hm.group("avg")),
                market_value=_num(hm.group("value")),
                allocation_pct=_num(hm.group("alloc")),
                currency=currency,
            )
        )

    # Reconcile: holdings should sum to the goal balances.
    goal_total = sum(b.balance for b in result.balances)
    holdings_total = sum(h.market_value for h in result.holdings)
    if result.balances and abs(goal_total - holdings_total) > 0.05:
        result.warnings.append(
            f"holdings total {holdings_total:.2f} != goal total {goal_total:.2f}"
        )

    return result
