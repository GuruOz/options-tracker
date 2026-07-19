"""Parse a CPF "Transaction history" PDF into balances + transactions.

Pure functions, no DB — mirrors ``clients/ibkr/csv_import.py``: tolerant, returns
normalised rows plus a ``warnings`` list, and never raises on layout drift
(unmatched date-rows are counted as warnings, header/footer noise is ignored).

The statement is a per-sub-account ledger (Ordinary / Special / MediSave). Each
row is either a ``BAL`` snapshot (opening on the first, closing on the last) or a
coded transaction (CON contribution, HSE housing, INV investment moved to a
platform like Endowus, INT interest, and assorted insurance/misc codes).

The person's name and CPF account number appear as repeated page headers/footers;
they are deliberately not extracted or persisted.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from pypdf import PdfReader

_PERIOD_RE = re.compile(
    r"From (\d{2} \w{3} \d{4}) to (\d{2} \w{3} \d{4})", re.IGNORECASE
)

# "01 May 2025 BAL 22,733.63 22,456.62 33,467.69"
# "15 May 2025 CON APR 2025 A 1,702.23 443.82 591.95"
# "11 May 2025 HSE -754.00 0.00 0.00"
_ROW_RE = re.compile(
    r"^(?P<date>\d{2} \w{3} \d{4}) "
    r"(?P<code>[A-Z]{2,5}) "
    r"(?:(?P<for_month>[A-Z]{3} \d{4}) )?"
    r"(?:(?P<ref>[A-Z]) )?"
    r"(?P<oa>-?[\d,]+\.\d{2}) (?P<sa>-?[\d,]+\.\d{2}) (?P<ma>-?[\d,]+\.\d{2})$"
)

_DATE_PREFIX_RE = re.compile(r"^\d{2} \w{3} \d{4}\b")
# Footer timestamp "19 Jul 2026 04:31 PM (Singapore Standard Time)" also starts
# with a date — recognise it so it isn't flagged as an unparsed data row.
_FOOTER_TS_RE = re.compile(r"^\d{2} \w{3} \d{4} \d{1,2}:\d{2} [AP]M")


@dataclass
class CpfBalance:
    as_of: date
    category: str  # "OA" | "SA" | "MA"
    balance: float


@dataclass
class CpfTransaction:
    txn_date: date
    code: str
    for_month: date | None
    ref: str | None
    oa_amount: float
    sa_amount: float
    ma_amount: float
    row_hash: str


@dataclass
class CpfParseResult:
    period_start: date | None
    period_end: date | None
    balances: list[CpfBalance] = field(default_factory=list)
    transactions: list[CpfTransaction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%d %b %Y").date()
    except ValueError:
        return None


def _parse_for_month(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%b %Y").date().replace(day=1)
    except ValueError:
        return None


def _row_hash(txn_date: date, code: str, for_month: date | None, ref: str | None,
             oa: float, sa: float, ma: float) -> str:
    raw = f"{txn_date.isoformat()}|{code}|{for_month or ''}|{ref or ''}|{oa}|{sa}|{ma}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _lines(content: bytes) -> list[str]:
    reader = PdfReader(_io(content))
    out: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        out.extend(line.strip() for line in text.splitlines() if line.strip())
    return out


def _io(content: bytes):
    import io
    return io.BytesIO(content)


def parse_cpf_pdf(content: bytes) -> CpfParseResult:
    lines = _lines(content)

    period_start = period_end = None
    for line in lines:
        m = _PERIOD_RE.search(line)
        if m:
            period_start = _parse_date(m.group(1))
            period_end = _parse_date(m.group(2))
            break

    result = CpfParseResult(period_start=period_start, period_end=period_end)

    bal_rows: list[tuple[date, float, float, float]] = []
    for line in lines:
        m = _ROW_RE.match(line)
        if not m:
            # Only a line that looks like a data row (starts with a date) but
            # failed to parse is worth flagging — headers/footers are expected.
            if _DATE_PREFIX_RE.match(line) and not _FOOTER_TS_RE.match(line):
                result.warnings.append(f"unparsed row: {line}")
            continue

        txn_date = _parse_date(m.group("date"))
        if txn_date is None:
            result.warnings.append(f"bad date: {line}")
            continue
        code = m.group("code")
        oa, sa, ma = _num(m.group("oa")), _num(m.group("sa")), _num(m.group("ma"))

        if code == "BAL":
            bal_rows.append((txn_date, oa, sa, ma))
            continue

        for_month = _parse_for_month(m.group("for_month"))
        ref = m.group("ref")
        result.transactions.append(
            CpfTransaction(
                txn_date=txn_date, code=code, for_month=for_month, ref=ref,
                oa_amount=oa, sa_amount=sa, ma_amount=ma,
                row_hash=_row_hash(txn_date, code, for_month, ref, oa, sa, ma),
            )
        )

    # Opening (first BAL) and closing (last BAL) snapshots, one row per sub-account.
    if bal_rows:
        for snap in ({bal_rows[0], bal_rows[-1]}):
            d, oa, sa, ma = snap
            result.balances.append(CpfBalance(as_of=d, category="OA", balance=oa))
            result.balances.append(CpfBalance(as_of=d, category="SA", balance=sa))
            result.balances.append(CpfBalance(as_of=d, category="MA", balance=ma))
    else:
        result.warnings.append("no BAL rows found")

    return result
