import defusedxml.common
import pytest
from pydantic import ValidationError

from app.api.routes.market import validate_symbol
from app.api.routes.settings import SettingsIn
from app.clients.ibkr.flex_parse import parse_flex_xml

_BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
]>
<lolz>&lol2;</lolz>
"""


def test_billion_laughs_rejected_not_expanded():
    with pytest.raises(defusedxml.common.DefusedXmlException):
        parse_flex_xml(_BILLION_LAUGHS, "U123")


@pytest.mark.parametrize("symbol", ["AAPL", "BRK.B", "^VIX", "EURUSD=X", "qqq"])
def test_validate_symbol_accepts_real_tickers(symbol):
    assert validate_symbol(symbol) == symbol.upper()


@pytest.mark.parametrize(
    "symbol",
    ["'; DROP TABLE executions;--", "A" * 13, "AAPL BAD", "<script>", ""],
)
def test_validate_symbol_rejects_bad_input(symbol):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        validate_symbol(symbol)
    assert exc_info.value.status_code == 400


_VALID_SETTINGS = {
    "signal": {
        "weights": {
            "iv_percentile": 0.34,
            "variance_premium": 0.20,
            "trend": 0.26,
            "rsi_drawdown": 0.20,
        },
        "thresholds": {"favorable": 66, "selective": 45},
        "variance_premium_full_spread": 0.20,
    },
    "alerts": {"take_profit_pct": 0.70, "expiry_dte": 2, "near_strike_cushion": 0.03},
    "bs": {"risk_free_rate": 0.045},
    "risk": {
        "scenario_move": -0.10,
        "index_symbol": "QQQ",
        "beta_map": {"QQQ": 1.0, "SPY": 0.85},
    },
    "underlyings": [{"conid": 1, "symbol": "QQQ", "description": ""}],
}


def test_settings_model_accepts_valid_payload():
    SettingsIn(**_VALID_SETTINGS)


def test_settings_model_rejects_unknown_top_level_key():
    bad = {**_VALID_SETTINGS, "evil": 1}
    with pytest.raises(ValidationError):
        SettingsIn(**bad)


def test_settings_model_rejects_out_of_range_take_profit_pct():
    bad = {**_VALID_SETTINGS, "alerts": {**_VALID_SETTINGS["alerts"], "take_profit_pct": 1.5}}
    with pytest.raises(ValidationError):
        SettingsIn(**bad)


def test_settings_model_rejects_out_of_range_expiry_dte():
    bad = {**_VALID_SETTINGS, "alerts": {**_VALID_SETTINGS["alerts"], "expiry_dte": 999}}
    with pytest.raises(ValidationError):
        SettingsIn(**bad)


def test_settings_model_rejects_unknown_nested_key():
    bad = {**_VALID_SETTINGS, "bs": {**_VALID_SETTINGS["bs"], "evil": 1}}
    with pytest.raises(ValidationError):
        SettingsIn(**bad)
