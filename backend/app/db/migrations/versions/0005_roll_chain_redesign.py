"""roll chain redesign point 3

Revision ID: 0005_roll_chain_redesign
Revises: 0004_roll_chain_unique
Create Date: 2026-06-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_roll_chain_redesign"
down_revision: Union[str, None] = "0004_roll_chain_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add columns to roll_chains
    op.add_column("roll_chains", sa.Column("strike", sa.Numeric(precision=20, scale=6), nullable=True))
    op.add_column("roll_chains", sa.Column("close_reason", sa.String(length=32), nullable=True))
    op.add_column("roll_chains", sa.Column("is_manual", sa.Boolean(), server_default="false", nullable=False))

    # 2. Modify roll_chain_legs
    op.alter_column("roll_chain_legs", "exec_id", existing_type=sa.String(length=64), nullable=True)
    op.alter_column("roll_chain_legs", "role", existing_type=sa.String(length=16), type_=sa.String(length=32))

    # 3. Create chain_adjustments table
    op.create_table(
        "chain_adjustments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chain_id", sa.String(length=64), nullable=False),
        sa.Column("adjustment_type", sa.String(length=32), nullable=False),
        sa.Column("exec_id", sa.String(length=64), nullable=True),
        sa.Column("close_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chain_id"], ["roll_chains.chain_id"], ),
        sa.PrimaryKeyConstraint("id")
    )
    op.create_index(op.f("ix_chain_adjustments_chain_id"), "chain_adjustments", ["chain_id"], unique=False)

    # 4. Backfill strike on roll_chains
    op.execute("""
        UPDATE roll_chains
        SET strike = (
            SELECT e.strike 
            FROM roll_chain_legs rcl 
            JOIN executions e ON rcl.exec_id = e.exec_id 
            WHERE rcl.chain_id = roll_chains.chain_id 
              AND rcl.role = 'open' 
            LIMIT 1
        )
    """)


def downgrade() -> None:
    op.drop_index(op.f("ix_chain_adjustments_chain_id"), table_name="chain_adjustments")
    op.drop_table("chain_adjustments")
    op.alter_column("roll_chain_legs", "role", existing_type=sa.String(length=32), type_=sa.String(length=16))
    op.drop_column("roll_chains", "is_manual")
    op.drop_column("roll_chains", "close_reason")
    op.drop_column("roll_chains", "strike")
