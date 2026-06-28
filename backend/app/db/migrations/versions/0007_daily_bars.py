"""daily bars (market-context chart cache)

Revision ID: 0007_daily_bars
Revises: 0006_income_adjustments
Create Date: 2026-06-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.migration_utils import has_table


revision: str = "0007_daily_bars"
down_revision: Union[str, None] = "0006_income_adjustments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if has_table("daily_bars"):
        return  # baseline create_all already made it (fresh database)
    op.create_table(
        "daily_bars",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conid", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("bar_date", sa.Date(), nullable=False),
        sa.Column("close", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("is_vix", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conid", "bar_date", name="uq_daily_bar_conid_date"),
    )
    op.create_index("ix_daily_bar_conid_date", "daily_bars", ["conid", "bar_date"], unique=False)
    op.create_index(op.f("ix_daily_bars_conid"), "daily_bars", ["conid"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_daily_bars_conid"), table_name="daily_bars")
    op.drop_index("ix_daily_bar_conid_date", table_name="daily_bars")
    op.drop_table("daily_bars")
