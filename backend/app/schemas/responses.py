"""Pydantic response models for the read API (serialised from ORM rows)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PositionOut(_ORM):
    conid: int
    symbol: str | None = None
    sec_type: str | None = None
    right: str | None = None
    strike: float | None = None
    expiry: date | None = None
    position: float | None = None
    avg_cost: float | None = None
    mark: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    iv: float | None = None
    greeks_source: str | None = None
    snapshot_ts: datetime | None = None


class AccountSummaryOut(_ORM):
    snapshot_ts: datetime | None = None
    net_liquidation: float | None = None
    available_funds: float | None = None
    excess_liquidity: float | None = None
    maintenance_margin: float | None = None
    buying_power: float | None = None
    cash: float | None = None
    leverage: float | None = None


class TradeOut(_ORM):
    exec_id: str
    conid: int | None = None
    symbol: str | None = None
    sec_type: str | None = None
    side: str | None = None
    right: str | None = None
    strike: float | None = None
    expiry: date | None = None
    qty: float | None = None
    price: float | None = None
    commission: float | None = None
    exec_time: datetime | None = None


class MarketOut(_ORM):
    conid: int
    symbol: str | None = None
    snapshot_ts: datetime | None = None
    price: float | None = None
    iv: float | None = None
    realized_vol: float | None = None
    iv_percentile: float | None = None
    iv_rank: float | None = None
    rsi14: float | None = None
    sma50: float | None = None
    sma200: float | None = None


class SignalOut(_ORM):
    underlying_conid: int
    symbol: str | None = None
    ts: datetime | None = None
    composite_score: float | None = None
    verdict: str | None = None
    sub_scores: dict | None = None


class SignalPointOut(_ORM):
    ts: datetime | None = None
    composite_score: float | None = None
    verdict: str | None = None
