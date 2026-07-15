"""roll-chain cycle credits (open / initial / cycle-base)

Revision ID: 0008_chain_cycle_credits
Revises: 0007_daily_bars
Create Date: 2026-07-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.migration_utils import has_column


revision: str = "0008_chain_cycle_credits"
down_revision: Union[str, None] = "0007_daily_bars"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MONEY = sa.Numeric(precision=20, scale=6)


def upgrade() -> None:
    # Values are filled in by the next roll-chain rebuild (the poller job rebuilds
    # from executions), so no backfill is needed here.
    if not has_column("roll_chains", "open_credit"):
        op.add_column(
            "roll_chains",
            sa.Column("open_credit", _MONEY, server_default="0", nullable=True),
        )
    if not has_column("roll_chains", "initial_credit"):
        op.add_column("roll_chains", sa.Column("initial_credit", _MONEY, nullable=True))
    if not has_column("roll_chains", "cycle_base_credit"):
        op.add_column(
            "roll_chains",
            sa.Column("cycle_base_credit", _MONEY, server_default="0", nullable=True),
        )


def downgrade() -> None:
    op.drop_column("roll_chains", "cycle_base_credit")
    op.drop_column("roll_chains", "initial_credit")
    op.drop_column("roll_chains", "open_credit")
