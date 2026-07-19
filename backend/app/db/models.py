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
    LargeBinary,
    Numeric,
    String,
    Text,
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
    # What feeds this account: 'ibkr' (live gateway), 'cpf' or 'endowus'
    # (statement-upload synthetic accounts). The whole household net-worth view is
    # additive over kinds; the options analytics only ever query kind='ibkr'.
    kind: Mapped[str] = mapped_column(String(16), default="ibkr", server_default="ibkr")
    # Which person this account belongs to ('guru' / 'wife' / ...). Null for IBKR
    # rows until assigned — the owner map falls back to the account's gateway id.
    owner: Mapped[str | None] = mapped_column(String(32))
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
    # The contract's own trading currency (e.g. "USD" for a US-listed option),
    # NOT the account's base currency - IBKR never converts trade-level prices.
    # See app/analytics/risk.py and app/analytics/income.py for why this matters.
    currency: Mapped[str | None] = mapped_column(String(8))
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
    # The contract's own trading currency - see Execution.currency above.
    currency: Mapped[str | None] = mapped_column(String(8))
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


class DailyBar(Base):
    """Daily close history for underlyings + VIX — backs the market-context chart.

    The market poller already fetches a 1y daily history every cycle (for the
    indicator math) but only persisted the latest point-in-time snapshot. Storing
    the daily closes here gives the 6-12 month price chart (50-day SMA overlay +
    VIX) a cache to read, honouring the spec's "panels read from the Postgres
    cache" principle instead of refetching on every request. Idempotent upsert by
    ``(conid, bar_date)``. VIX is stored under a synthetic conid with
    ``is_vix=True`` and queried by that flag (it is market-wide, not per-symbol).
    """

    __tablename__ = "daily_bars"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conid: Mapped[int] = mapped_column(BigInteger, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32))
    bar_date: Mapped[date] = mapped_column(Date)
    close: Mapped[float | None] = mapped_column(Money)
    is_vix: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source: Mapped[str | None] = mapped_column(String(16))  # ibkr / public

    __table_args__ = (
        UniqueConstraint("conid", "bar_date", name="uq_daily_bar_conid_date"),
        Index("ix_daily_bar_conid_date", "conid", "bar_date"),
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
    # Cycle economics for a rolled short. A roll doesn't bank the new leg's
    # credit — it only banks the decay on the leg it replaces — so the numbers
    # the cockpit reports have to separate what's realized from what's still
    # riding on the open leg. See `analytics/rolls.py` for how they're kept.
    #   open_credit        sell credit of the short leg open right now (0 if flat)
    #   initial_credit     the sale that started this cycle — the premium the
    #                      whole cycle is working toward
    #   cycle_base_credit  cumulative_credit as of the cycle's start, so an
    #                      earlier cycle's P&L doesn't count toward this one
    open_credit: Mapped[float | None] = mapped_column(
        Money, default=0.0, server_default="0"
    )
    initial_credit: Mapped[float | None] = mapped_column(Money)
    cycle_base_credit: Mapped[float | None] = mapped_column(
        Money, default=0.0, server_default="0"
    )
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


class StatementUpload(Base):
    """One uploaded CPF/Endowus statement PDF. `file_sha256` is unique so the
    same file re-uploaded is a no-op (idempotent ingestion)."""

    __tablename__ = "statement_uploads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.account_id"), index=True
    )
    source: Mapped[str] = mapped_column(String(16))  # cpf | endowus
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    filename: Mapped[str | None] = mapped_column(String(256))
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    summary: Mapped[dict | None] = mapped_column(JSONB)


class ExternalBalance(Base):
    """A point-in-time balance snapshot for a non-IBKR account: CPF sub-account
    (OA/SA/MA) closing balances, or an Endowus goal ending balance. The household
    net worth sums the latest of these per account (never double-counting a CPF
    investment that now lives in Endowus)."""

    __tablename__ = "external_balances"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.account_id"), index=True
    )
    as_of: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(64))  # OA|SA|MA | goal name | TOTAL
    balance: Mapped[float | None] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(8), default="SGD", server_default="SGD")
    upload_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("statement_uploads.id")
    )

    __table_args__ = (
        UniqueConstraint("account_id", "as_of", "category", name="uq_ext_bal"),
        Index("ix_ext_bal_account_asof", "account_id", "as_of"),
    )


class CpfTransaction(Base):
    """One CPF ledger row (contribution, housing, investment, interest, ...).
    Deduped by (account, row_hash) so overlapping statements don't double-insert."""

    __tablename__ = "cpf_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.account_id"), index=True
    )
    txn_date: Mapped[date] = mapped_column(Date)
    code: Mapped[str] = mapped_column(String(8))
    for_month: Mapped[date | None] = mapped_column(Date)
    ref: Mapped[str | None] = mapped_column(String(8))
    oa_amount: Mapped[float | None] = mapped_column(Money)
    sa_amount: Mapped[float | None] = mapped_column(Money)
    ma_amount: Mapped[float | None] = mapped_column(Money)
    upload_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("statement_uploads.id")
    )
    row_hash: Mapped[str] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint("account_id", "row_hash", name="uq_cpf_txn"),
        Index("ix_cpf_txn_account_date", "account_id", "txn_date"),
    )


class ExternalHolding(Base):
    """An Endowus per-fund snapshot (fund, asset class, funding source, units,
    NAV, market value, allocation %). Backs the allocation breakdown; the money
    total comes from `ExternalBalance` goal balances, not from summing these."""

    __tablename__ = "external_holdings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.account_id"), index=True
    )
    as_of: Mapped[date] = mapped_column(Date)
    goal_name: Mapped[str | None] = mapped_column(String(128))
    fund_name: Mapped[str | None] = mapped_column(String(256))
    asset_class: Mapped[str | None] = mapped_column(String(64))
    funding_source: Mapped[str | None] = mapped_column(String(32))
    units: Mapped[float | None] = mapped_column(Money)
    nav: Mapped[float | None] = mapped_column(Money)
    avg_price: Mapped[float | None] = mapped_column(Money)
    market_value: Mapped[float | None] = mapped_column(Money)
    allocation_pct: Mapped[float | None] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(8), default="SGD", server_default="SGD")
    upload_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("statement_uploads.id")
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id", "as_of", "goal_name", "fund_name", "funding_source",
            name="uq_ext_holding",
        ),
        Index("ix_ext_holding_account_asof", "account_id", "as_of"),
    )


class DashboardLayout(Base):
    """The saved home-dashboard widget layout for one scope ('all' or an owner
    slug). One row per scope; the frontend falls back to a default layout when a
    scope has none."""

    __tablename__ = "dashboard_layouts"

    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    layout: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CashflowEntry(Base):
    """Simple monthly income/expenses per owner (or 'household'). Feeds the FIRE
    projection's savings rate. One row per (owner, month)."""

    __tablename__ = "cashflow_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner: Mapped[str] = mapped_column(String(32), index=True)
    month: Mapped[date] = mapped_column(Date)  # first of month
    income: Mapped[float | None] = mapped_column(Money)
    expenses: Mapped[float | None] = mapped_column(Money)
    note: Mapped[str | None] = mapped_column(String(256))

    __table_args__ = (
        UniqueConstraint("owner", "month", name="uq_cashflow_owner_month"),
    )


class PlanSettings(Base):
    """FIRE-planning inputs for one owner (or 'household'): ages, target income,
    withdrawal rate, expected/pessimistic/optimistic returns. JSON blob so the
    parameter set can grow without a migration."""

    __tablename__ = "plan_settings"

    owner: Mapped[str] = mapped_column(String(32), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AiConfig(Base):
    """BYO-key config for the AI advisor (single row, id=1). The API key is
    stored Fernet-encrypted and never returned to the client."""

    __tablename__ = "ai_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    provider: Mapped[str | None] = mapped_column(String(16))  # anthropic | openai_compat
    base_url: Mapped[str | None] = mapped_column(String(256))
    model: Mapped[str | None] = mapped_column(String(64))
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AiSuggestion(Base):
    """A generated set of suggested moves. `input_summary` is the anonymized
    payload actually sent to the model (audit trail)."""

    __tablename__ = "ai_suggestions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    provider: Mapped[str | None] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str | None] = mapped_column(Text)
    input_summary: Mapped[dict | None] = mapped_column(JSONB)


class Setting(Base):
    """Single-row JSON blob of market-wide settings (id is always 1).

    Holds only what is genuinely shared across accounts: signal weights (they
    produce the one conid-keyed `signal_history` every user reads), the
    Black-Scholes fallback rate, and the risk beta map / scenario. Per-user keys
    (`underlyings`, `alerts`) live in `AccountSetting`.
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    data: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuthSession(Base):
    """A live login for the single shared account. token_hash is a sha256 of
    the raw session cookie value — only the hash is ever persisted."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    client: Mapped[str | None] = mapped_column(String(255))  # truncated user-agent


class AccountSetting(Base):
    """Per-account settings: the tracked-underlying watchlist + alert thresholds.

    Each user curates their own watchlist and tunes their own take-profit /
    expiry / cushion thresholds. The market poller fetches the *union* of every
    account's watchlist, since the resulting market data is conid-keyed and
    shared by everyone.
    """

    __tablename__ = "account_settings"

    account_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("accounts.account_id"), primary_key=True
    )
    data: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
