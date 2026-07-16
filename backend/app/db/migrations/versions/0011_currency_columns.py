"""per-trade/position currency

Adds `currency` to `executions` and `positions_snapshots` - the contract's own
trading currency (e.g. "USD" for a US-listed option), which IBKR reports
separately from the account's base currency and never converts. Needed so the
analytics layer can tell when it would otherwise be dividing figures in two
different currencies (see app/analytics/risk.py, app/analytics/income.py).

No backfill: existing rows get NULL, which analytics treats as "unknown" and
leaves ungated (same behavior as before this migration) rather than guessing.

Revision ID: 0011_currency_columns
Revises: 0010_auth_sessions
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.migration_utils import has_column


revision: str = "0011_currency_columns"
down_revision: Union[str, None] = "0010_auth_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not has_column("executions", "currency"):
        op.add_column("executions", sa.Column("currency", sa.String(length=8), nullable=True))
    if not has_column("positions_snapshots", "currency"):
        op.add_column("positions_snapshots", sa.Column("currency", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("positions_snapshots", "currency")
    op.drop_column("executions", "currency")
