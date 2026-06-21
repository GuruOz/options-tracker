"""SQLAlchemy models — the persisted schema for unbounded history.

Every history table carries `account_id` so a future multi-account (one gateway
per account) deployment is additive rather than a rewrite.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# A wide-but-bounded numeric for money/greeks. Precision over float drift.
Money = Numeric(20, 6)
Greek = Numeric(14, 6)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    label: Mapped[str | None] = mapped_column(String(128))
    base_currency: Mapped[str | None] = mapped_column(String(8))
    is_paper: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    meta: Mapped[dict | None] = mapped_column(JSONB)


class Execution(Base):
    """Every fill. Append-only, deduped by `exec_id` -> unbounded history."""

    __tablename__ = "executions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exec_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.account_id"), index=True
    )
    conid: Mapped[int | None] = mapped_column(BigInteger, index=True)
    symbol: Mapped[str | None] = mapped_column(String(64))
    sec_type: Mapped[str | None] = mapped_column(String(16))
    side: Mapped[str | None] = mapped_column(String(4))   # B / S
    right: Mapped[str | None] = mapped_column(String(1))  # P / C (options)
    strike: Mapped[float | None] = mapped_column(Money)
    expiry: Mapped[date | None] = mapped_column(Date)
    qty: Mapped[float | None] = mapped_column(Money)
    price: Mapped[float | None] = mapped_column(Money)
    commission: Mapped[float | None] = mapped_column(Money)
    realized_pnl: Mapped[float | None] = mapped_column(Money)
    exec_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(16))  # poll / flex_import
    raw: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_executions_account_time", "account_id", "exec_time"),
        Index("ix_executions_conid_time", "conid", "exec_time"),
    )


class PositionSnapshot(Base):
    __tablename__ = "positions_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.account_id"), index=True
    )
    conid: Mapped[int] = mapped_column(BigInteger, index=True)
    snapshot_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sec_type: Mapped[str | None] = mapped_column(String(16))
    symbol: Mapped[str | None] = mapped_column(String(64))
    right: Mapped[str | None] = mapped_column(String(1))
    strike: Mapped[float | None] = mapped_column(Money)
    expiry: Mapped[date | None] = mapped_column(Date)
    position: Mapped[float | None] = mapped_column(Money)  # signed qty
    avg_cost: Mapped[float | None] = mapped_column(Money)
    mark: Mapped[float | None] = mapped_column(Money)
    market_value: Mapped[float | None] = mapped_column(Money)
    unrealized_pnl: Mapped[float | None] = mapped_column(Money)
    delta: Mapped[float | None] = mapped_column(Greek)
    gamma: Mapped[float | None] = mapped_column(Greek)
    theta: Mapped[float | None] = mapped_column(Greek)
    vega: Mapped[float | None] = mapped_column(Greek)
    iv: Mapped[float | None] = mapped_column(Greek)
    greeks_source: Mapped[str | None] = mapped_column(String(8))  # ibkr / bs_est
    raw: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_positions_account_time", "account_id", "snapshot_ts"),
        Index("ix_positions_conid_time", "conid", "snapshot_ts"),
    )


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.account_id"), index=True
    )
    snapshot_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    net_liquidation: Mapped[float | None] = mapped_column(Money)
    available_funds: Mapped[float | None] = mapped_column(Money)
    excess_liquidity: Mapped[float | None] = mapped_column(Money)
    maintenance_margin: Mapped[float | None] = mapped_column(Money)
    buying_power: Mapped[float | None] = mapped_column(Money)
    leverage: Mapped[float | None] = mapped_column(Greek)
    cash: Mapped[float | None] = mapped_column(Money)
    raw: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_account_snap_account_time", "account_id", "snapshot_ts"),
    )


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conid: Mapped[int] = mapped_column(BigInteger, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32))
    snapshot_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[float | None] = mapped_column(Money)
    iv: Mapped[float | None] = mapped_column(Greek)
    realized_vol: Mapped[float | None] = mapped_column(Greek)
    iv_percentile: Mapped[float | None] = mapped_column(Greek)
    iv_rank: Mapped[float | None] = mapped_column(Greek)
    rsi14: Mapped[float | None] = mapped_column(Greek)
    sma50: Mapped[float | None] = mapped_column(Money)
    sma200: Mapped[float | None] = mapped_column(Money)
    is_vix: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source: Mapped[str | None] = mapped_column(String(16))  # ibkr / public / cache
    raw: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_market_conid_time", "conid", "snapshot_ts"),
    )


class SignalHistory(Base):
    """Composite score plus every sub-score, raw input, and weight used.

    Persisting the inputs+weights makes each score reproducible and back-testable.
    """

    __tablename__ = "signal_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    underlying_conid: Mapped[int] = mapped_column(BigInteger, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    composite_score: Mapped[float | None] = mapped_column(Greek)
    verdict: Mapped[str | None] = mapped_column(String(16))  # FAVORABLE/SELECTIVE/WAIT
    sub_scores: Mapped[dict | None] = mapped_column(JSONB)
    inputs: Mapped[dict | None] = mapped_column(JSONB)
    weights: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_signal_underlying_ts", "underlying_conid", "ts"),
    )


class RollChain(Base):
    """A logical position grouping buy-to-close + sell-to-open legs."""

    __tablename__ = "roll_chains"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.account_id"), index=True
    )
    underlying_symbol: Mapped[str | None] = mapped_column(String(32))
    underlying_conid: Mapped[int | None] = mapped_column(BigInteger)
    right: Mapped[str | None] = mapped_column(String(1))
    strike: Mapped[float | None] = mapped_column(Money)
    status: Mapped[str | None] = mapped_column(String(16))  # open/closed/assigned
    close_reason: Mapped[str | None] = mapped_column(String(32))
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cumulative_credit: Mapped[float | None] = mapped_column(Money)
    meta: Mapped[dict | None] = mapped_column(JSONB)


class RollChainLeg(Base):
    __tablename__ = "roll_chain_legs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("roll_chains.chain_id"), index=True
    )
    exec_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("executions.exec_id")
    )
    conid: Mapped[int | None] = mapped_column(BigInteger)
    role: Mapped[str | None] = mapped_column(String(32))  # open/close/roll/assignment/expired/assignment_stock/stock_close
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("chain_id", "exec_id", name="uq_chain_exec"),
    )


class ChainAdjustment(Base):
    """User overrides for the roll chain builder."""

    __tablename__ = "chain_adjustments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chain_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("roll_chains.chain_id"), index=True
    )
    adjustment_type: Mapped[str] = mapped_column(String(32))  # manual_link, manual_close, manual_split
    exec_id: Mapped[str | None] = mapped_column(String(64))  # For link/split
    close_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True)) # For close
    close_reason: Mapped[str | None] = mapped_column(String(32)) # For close
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OptionMeta(Base):
    __tablename__ = "option_meta"

    conid: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    underlying_symbol: Mapped[str | None] = mapped_column(String(32))
    underlying_conid: Mapped[int | None] = mapped_column(BigInteger)
    right: Mapped[str | None] = mapped_column(String(1))
    strike: Mapped[float | None] = mapped_column(Money)
    expiry: Mapped[date | None] = mapped_column(Date)
    multiplier: Mapped[int | None] = mapped_column(Integer, default=100)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class IncomeAdjustment(Base):
    """Per-month manual overlay for the premium-income panel.

    One row per (account, month). Holds the user's "cashed out?" flag, an
    optional withdrawal amount, and a free note — the only user-entered data in
    the app. Monthly/yearly P&L itself is derived from roll chains, not stored.
    """

    __tablename__ = "income_adjustments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.account_id"), index=True
    )
    month: Mapped[date] = mapped_column(Date)  # first day of the month
    cashed_out: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    withdrawal_amount: Mapped[float | None] = mapped_column(Money)
    note: Mapped[str | None] = mapped_column(String(256))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("account_id", "month", name="uq_income_account_month"),
    )


class Setting(Base):
    """Single-row JSON blob of user-configurable settings (id is always 1)."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    data: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
