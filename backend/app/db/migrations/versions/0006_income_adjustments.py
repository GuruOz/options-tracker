"""income adjustments (premium-income panel manual overlay)

Revision ID: 0006_income_adjustments
Revises: 0005_roll_chain_redesign
Create Date: 2026-06-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_income_adjustments"
down_revision: Union[str, None] = "0005_roll_chain_redesign"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "income_adjustments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("cashed_out", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("withdrawal_amount", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("note", sa.String(length=256), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "month", name="uq_income_account_month"),
    )
    op.create_index(op.f("ix_income_adjustments_account_id"), "income_adjustments", ["account_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_income_adjustments_account_id"), table_name="income_adjustments")
    op.drop_table("income_adjustments")
