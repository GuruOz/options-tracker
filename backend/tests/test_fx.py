"""Unit tests for the live FX-rate service (`app/core/fx.py`)."""
import asyncio

import pytest

from app.core import fx


@pytest.fixture(autouse=True)
def _clean_fx_state():
    fx._cache.clear()
    fx._last_known.clear()
    fx._fetch_attempt.clear()
    yield
    fx._cache.clear()
    fx._last_known.clear()
    fx._fetch_attempt.clear()


def _stub_fetchers(monkeypatch, ibkr=None, yahoo=None):
    """Install counting fetcher stubs; None means the feed is down."""
    calls = {"ibkr": 0, "yahoo": 0}

    async def fake_ibkr(src, dst):
        calls["ibkr"] += 1
        return ibkr

    def fake_yahoo(src, dst):
        calls["yahoo"] += 1
        return yahoo

    monkeypatch.setattr(fx, "_fetch_ibkr_rate", fake_ibkr)
    monkeypatch.setattr(fx, "_fetch_yf_rate_sync", fake_yahoo)
    return calls


def test_identity_pair_never_fetches(monkeypatch):
    calls = _stub_fetchers(monkeypatch, ibkr=1.35)
    rate = asyncio.run(fx.get_rate("USD", "USD"))
    assert rate.rate == 1.0
    assert rate.source == "identity"
    assert calls == {"ibkr": 0, "yahoo": 0}


def test_ibkr_rate_cached_within_ttl(monkeypatch):
    calls = _stub_fetchers(monkeypatch, ibkr=1.35)
    first = asyncio.run(fx.get_rate("USD", "SGD"))
    second = asyncio.run(fx.get_rate("USD", "SGD"))
    assert first.rate == 1.35
    assert first.source == "ibkr"
    assert second.rate == 1.35
    assert calls["ibkr"] == 1  # served from cache the second time
    assert calls["yahoo"] == 0


def test_ttl_expiry_refetches(monkeypatch):
    calls = _stub_fetchers(monkeypatch, ibkr=1.35)
    asyncio.run(fx.get_rate("USD", "SGD"))
    monkeypatch.setattr(fx, "_FX_TTL_SECONDS", 0)
    asyncio.run(fx.get_rate("USD", "SGD"))
    assert calls["ibkr"] == 2


def test_yahoo_fallback_when_ibkr_down(monkeypatch):
    calls = _stub_fetchers(monkeypatch, ibkr=None, yahoo=1.34)
    rate = asyncio.run(fx.get_rate("USD", "SGD"))
    assert rate.rate == 1.34
    assert rate.source == "public"
    assert calls == {"ibkr": 1, "yahoo": 1}


def test_stale_last_known_served_when_both_feeds_down(monkeypatch):
    _stub_fetchers(monkeypatch, ibkr=1.35)
    asyncio.run(fx.get_rate("USD", "SGD"))

    monkeypatch.setattr(fx, "_FX_TTL_SECONDS", 0)  # expire the fresh cache
    _stub_fetchers(monkeypatch)  # both feeds down now
    rate = asyncio.run(fx.get_rate("USD", "SGD"))
    assert rate.rate == 1.35
    assert rate.source == "cache"


def test_unknown_pair_with_dead_feeds_returns_none(monkeypatch):
    _stub_fetchers(monkeypatch)
    assert asyncio.run(fx.get_rate("USD", "SGD")) is None


def test_inverse_pair_resolution(monkeypatch):
    _stub_fetchers(monkeypatch, ibkr=1.35)
    asyncio.run(fx.get_rate("USD", "SGD"))

    _stub_fetchers(monkeypatch)  # SGD/USD itself can't be fetched
    rate = asyncio.run(fx.get_rate("SGD", "USD"))
    assert rate is not None
    assert round(rate.rate, 6) == round(1 / 1.35, 6)


def test_rate_map_drops_unresolvable_pairs(monkeypatch):
    _stub_fetchers(monkeypatch, ibkr=1.35)
    rates = asyncio.run(fx.rate_map({("USD", "SGD"), ("USD", "USD")}))
    assert rates[("USD", "SGD")].rate == 1.35
    assert rates[("USD", "USD")].rate == 1.0

    fx._cache.clear()
    fx._last_known.clear()
    fx._fetch_attempt.clear()
    _stub_fetchers(monkeypatch)
    rates = asyncio.run(fx.rate_map({("USD", "SGD")}))
    assert rates == {}
