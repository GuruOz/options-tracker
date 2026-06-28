"""add source column to market_snapshots

Revision ID: 0003_add_market_source
Revises: 0002_widen_symbol
Create Date: 2026-06-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.migration_utils import has_column


revision: str = "0003_add_market_source"
down_revision: Union[str, None] = "0002_widen_symbol"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Skip if the baseline create_all already added it (fresh database).
    if not has_column("market_snapshots", "source"):
        op.add_column(
            "market_snapshots",
            sa.Column("source", sa.String(16), nullable=True),
        )


def downgrade() -> None:
    if has_column("market_snapshots", "source"):
        op.drop_column("market_snapshots", "source")
