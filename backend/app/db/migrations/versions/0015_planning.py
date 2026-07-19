"""cashflow entries + FIRE plan settings

Adds the two planning tables:
  * cashflow_entries — monthly income/expenses per owner (or 'household')
  * plan_settings    — FIRE inputs per owner (JSON blob)

Guarded with has_table so a fresh database (baseline create_all) doesn't collide.

Revision ID: 0015_planning
Revises: 0014_dashboard_layouts
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.migration_utils import has_table


revision: str = "0015_planning"
down_revision: Union[str, None] = "0014_dashboard_layouts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MONEY = sa.Numeric(20, 6)


def upgrade() -> None:
    if not has_table("cashflow_entries"):
        op.create_table(
            "cashflow_entries",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("owner", sa.String(length=32), nullable=False),
            sa.Column("month", sa.Date(), nullable=False),
            sa.Column("income", _MONEY, nullable=True),
            sa.Column("expenses", _MONEY, nullable=True),
            sa.Column("note", sa.String(length=256), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("owner", "month", name="uq_cashflow_owner_month"),
        )
        op.create_index("ix_cashflow_entries_owner", "cashflow_entries", ["owner"])

    if not has_table("plan_settings"):
        op.create_table(
            "plan_settings",
            sa.Column("owner", sa.String(length=32), nullable=False),
            sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("owner"),
        )


def downgrade() -> None:
    op.drop_table("plan_settings")
    op.drop_table("cashflow_entries")
