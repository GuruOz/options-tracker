"""add unique constraint to roll_chain_legs (chain_id, exec_id)

Revision ID: 0004_roll_chain_unique
Revises: 0003_add_market_source
Create Date: 2026-06-20
"""
from typing import Sequence, Union

from alembic import op

from app.db.migration_utils import has_constraint


revision: str = "0004_roll_chain_unique"
down_revision: Union[str, None] = "0003_add_market_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not has_constraint("roll_chain_legs", "uq_chain_exec"):
        op.create_unique_constraint(
            "uq_chain_exec", "roll_chain_legs", ["chain_id", "exec_id"]
        )


def downgrade() -> None:
    if has_constraint("roll_chain_legs", "uq_chain_exec"):
        op.drop_constraint("uq_chain_exec", "roll_chain_legs", type_="unique")
