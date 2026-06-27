"""Pydantic response models for the read API (serialised from ORM rows)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DecayPoint(BaseModel):
    dte: int
    extrinsic: float


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
    dte: int | None = None
    underlying_price: float | None = None
    premium_captured_pct: float | None = None
    cushion_pct: float | None = None
    intrinsic_value: float | None = None
    extrinsic_value: float | None = None
    decay_curve: list[DecayPoint] | None = None
    status: str | None = None
    chain_id: str | None = None
    source: str | None = None
    last_updated: datetime | None = None


class AccountSummaryOut(_ORM):
    snapshot_ts: datetime | None = None
    net_liquidation: float | None = None
    available_funds: float | None = None
    excess_liquidity: float | None = None
    maintenance_margin: float | None = None
    buying_power: float | None = None
    cash: float | None = None
    leverage: float | None = None
    source: str | None = None
    last_updated: datetime | None = None


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
    source: str | None = None


class MarketHistoryPointOut(BaseModel):
    date: date
    close: float | None = None
    sma: float | None = None
    sma200: float | None = None
    vix: float | None = None


class MarketHistoryOut(BaseModel):
    conid: int
    symbol: str | None = None
    months: int
    sma_window: int = 50
    points: list[MarketHistoryPointOut] = []
    market: MarketOut | None = None


class SignalOut(_ORM):
    underlying_conid: int
    symbol: str | None = None
    ts: datetime | None = None
    composite_score: float | None = None
    verdict: str | None = None
    sub_scores: dict | None = None
    source: str | None = None


class SignalPointOut(_ORM):
    ts: datetime | None = None
    composite_score: float | None = None
    verdict: str | None = None


class RiskPositionOut(BaseModel):
    symbol: str | None = None
    sec_type: str | None = None
    right: str | None = None
    strike: float | None = None
    beta: float | None = None
    delta_dollars: float | None = None
    beta_weighted_delta_dollars: float | None = None
    scenario_pnl: float | None = None


class AssignmentOut(BaseModel):
    total_obligation: float | None = None
    cash: float | None = None
    coverage_ratio: float | None = None
    short_put_count: int = 0


class EquityPointOut(BaseModel):
    ts: datetime | None = None
    net_liquidation: float | None = None


class RiskOut(BaseModel):
    scenario_move: float
    index_symbol: str | None = None
    net_liquidation: float | None = None
    beta_weighted_delta_dollars: float | None = None
    gross_delta_dollars: float | None = None
    scenario_pnl: float | None = None
    scenario_pnl_pct: float | None = None
    assignment: AssignmentOut
    positions: list[RiskPositionOut] = []
    equity_curve: list[EquityPointOut] = []
