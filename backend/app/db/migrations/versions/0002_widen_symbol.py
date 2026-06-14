"""widen symbol columns to 64 chars

Option contract descriptions (and some symbols) exceed VARCHAR(32).

Revision ID: 0002_widen_symbol
Revises: 0001_initial
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_widen_symbol"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("positions_snapshots", "symbol", type_=sa.String(64))
    op.alter_column("executions", "symbol", type_=sa.String(64))


def downgrade() -> None:
    op.alter_column("positions_snapshots", "symbol", type_=sa.String(32))
    op.alter_column("executions", "symbol", type_=sa.String(32))
