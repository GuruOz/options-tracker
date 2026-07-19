"""Parser tests against the real (redacted) sample statements in fixtures/.

These assert the exact figures a human can read off the PDFs, so a layout-drift
regression in the regexes is caught immediately.
"""
from pathlib import Path

import pytest

from app.clients.statements.cpf_pdf import parse_cpf_pdf
from app.clients.statements.endowus_pdf import parse_endowus_pdf

FIXTURES = Path(__file__).parent / "fixtures"
CPF = FIXTURES / "cpf_sample.pdf"
ENDOWUS = FIXTURES / "endowus_sample.pdf"

pytestmark = pytest.mark.skipif(
    not CPF.exists() or not ENDOWUS.exists(),
    reason="sample statement fixtures not present",
)


def _closing(balances):
    """{'OA'|'SA'|'MA': balance} for the latest as_of date."""
    latest = max(b.as_of for b in balances)
    return {b.category: b.balance for b in balances if b.as_of == latest}


def test_cpf_closing_balances():
    r = parse_cpf_pdf(CPF.read_bytes())
    assert (r.period_start, r.period_end) is not None
    closing = _closing(r.balances)
    assert closing["OA"] == pytest.approx(33220.06)
    assert closing["SA"] == pytest.approx(31186.71)
    assert closing["MA"] == pytest.approx(46207.97)


def test_cpf_transactions_parsed_cleanly():
    r = parse_cpf_pdf(CPF.read_bytes())
    assert len(r.transactions) == 73
    codes = {t.code for t in r.transactions}
    assert {"CON", "HSE", "INV", "INT"} <= codes
    # CON rows carry a for-month + ref letter; others don't.
    con = next(t for t in r.transactions if t.code == "CON")
    assert con.for_month is not None and con.ref in {"A", "B", "C"}
    # Header/footer noise must not be mistaken for data rows.
    assert r.warnings == []


def test_cpf_row_hash_is_deterministic():
    a = parse_cpf_pdf(CPF.read_bytes())
    b = parse_cpf_pdf(CPF.read_bytes())
    assert [t.row_hash for t in a.transactions] == [t.row_hash for t in b.transactions]
    assert len({t.row_hash for t in a.transactions}) == len(a.transactions)


def test_endowus_holdings_and_goal_balance():
    r = parse_endowus_pdf(ENDOWUS.read_bytes())
    assert r.period_start.isoformat() == "2026-06-01"
    assert r.period_end.isoformat() == "2026-06-30"

    # Two funds, de-duped across the repeated tables, summing to the goal total.
    assert len(r.holdings) == 2
    total = sum(h.market_value for h in r.holdings)
    assert total == pytest.approx(7262.17)

    goal_total = sum(b.balance for b in r.balances)
    assert goal_total == pytest.approx(7262.17)

    world = next(h for h in r.holdings if "World" in h.fund_name)
    assert world.asset_class == "Equity Fund"
    assert world.funding_source == "CPF OA"
    assert world.market_value == pytest.approx(5442.68)
    assert r.warnings == []


def test_endowus_currency_detected_sgd():
    r = parse_endowus_pdf(ENDOWUS.read_bytes())
    # This statement's display currency is SGD; balances/holdings carry it.
    assert r.currency == "SGD"
    assert all(b.currency == "SGD" for b in r.balances)
    assert all(h.currency == "SGD" for h in r.holdings)
