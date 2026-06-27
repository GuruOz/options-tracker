"""Cross-source execution de-duplication rules (`analytics/dedup.py`)."""
from app.analytics.dedup import (
    content_key,
    is_authoritative,
    is_superseded_poll_row,
    option_content_key,
    superseded_poll_exec_ids,
)


def _row(exec_id, source, *, conid=111, side="S", qty=1, price=8.65,
         sec_type="OPT", symbol="NVDA"):
    return {
        "exec_id": exec_id, "source": source, "conid": conid, "side": side,
        "qty": qty, "price": price, "sec_type": sec_type, "symbol": symbol,
    }


def test_content_key_is_feed_independent():
    # Same contract/side/qty/price -> same key regardless of feed, exec_id, or
    # how the symbol was spelled. Case/precision differences don't matter.
    flex = content_key(conid=111, side="S", qty=1, price=8.65)
    poll = content_key(conid=111, side="s", qty=1.0, price=8.6500)
    assert flex is not None and flex == poll


def test_content_key_distinguishes_contracts_sides_qty_price():
    base = content_key(conid=111, side="S", qty=1, price=8.65)
    assert base != content_key(conid=222, side="S", qty=1, price=8.65)
    assert base != content_key(conid=111, side="B", qty=1, price=8.65)
    assert base != content_key(conid=111, side="S", qty=2, price=8.65)
    assert base != content_key(conid=111, side="S", qty=1, price=6.33)


def test_content_key_none_when_incomplete():
    assert content_key(conid=None, side="S", qty=1, price=8.65) is None
    assert content_key(conid=111, side=None, qty=1, price=8.65) is None
    assert content_key(conid=111, side="S", qty=None, price=8.65) is None
    assert content_key(conid=111, side="S", qty=1, price=None) is None


def test_option_content_key_scoped_to_options():
    assert option_content_key(_row("a", "poll")) is not None
    assert option_content_key(_row("a", "poll", sec_type="STK")) is None


def test_is_authoritative():
    assert all(is_authoritative(s) for s in ("flex", "flex_eae", "flex_import"))
    assert not is_authoritative("poll")
    assert not is_authoritative(None)


def test_drops_poll_twins_only_the_reported_scenario():
    # The exact case from the trades view: a 215/216 roll arrives via Flex (full
    # OCC symbol) and again via the poll (bare "NVDA", no strike). Drop the two
    # poll copies; keep both Flex rows.
    execs = [
        _row("106609582", "flex", conid=215, side="S", price=8.65),
        _row("106609482", "flex", conid=216, side="B", price=6.33),
        _row("00014248.6a31403f.02.01", "poll", conid=215, side="S", price=8.65),
        _row("00014248.6a31403f.03.01", "poll", conid=216, side="B", price=6.33),
    ]
    assert set(superseded_poll_exec_ids(execs)) == {
        "00014248.6a31403f.02.01",
        "00014248.6a31403f.03.01",
    }


def test_keeps_authoritative_and_unmatched_poll():
    assert superseded_poll_exec_ids([_row("flex1", "flex"), _row("poll1", "poll")]) == ["poll1"]
    # No authoritative twin -> nothing dropped.
    assert superseded_poll_exec_ids([_row("poll1", "poll")]) == []


def test_ignores_stock_and_keyless_rows():
    execs = [
        _row("flex_stk", "flex", sec_type="STK", price=200.0),
        _row("poll_stk", "poll", sec_type="STK", price=200.0),  # STK: not cross-matched
        _row("flex_opt", "flex", conid=None),                   # keyless: ignored
        _row("poll_opt", "poll", conid=None),                   # keyless: kept
    ]
    assert superseded_poll_exec_ids(execs) == []


def test_is_superseded_poll_row():
    auth_keys = {option_content_key(_row("x", "flex", price=8.65))}
    assert is_superseded_poll_row(_row("p", "poll", price=8.65), auth_keys) is True
    assert is_superseded_poll_row(_row("p", "poll", price=1.23), auth_keys) is False
    # An authoritative row is never treated as a superseded poll dup.
    assert is_superseded_poll_row(_row("f", "flex", price=8.65), auth_keys) is False
