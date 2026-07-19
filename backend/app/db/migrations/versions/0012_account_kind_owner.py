"""account kind + owner discriminators

Adds `kind` ('ibkr'|'cpf'|'endowus') and `owner` (person slug) to `accounts`,
so the same table can hold IBKR live accounts alongside the CPF/Endowus
statement-upload synthetic accounts introduced for the finance-tracker pivot.

`kind` defaults to 'ibkr' (every existing row is an IBKR account). `owner` is
left NULL on existing rows — the owner map resolves an unset owner to the
account's gateway id at request time, so no data backfill is required here.

Revision ID: 0012_account_kind_owner
Revises: 0011_currency_columns
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.migration_utils import has_column


revision: str = "0012_account_kind_owner"
down_revision: Union[str, None] = "0011_currency_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not has_column("accounts", "kind"):
        op.add_column(
            "accounts",
            sa.Column(
                "kind", sa.String(length=16), server_default="ibkr", nullable=False
            ),
        )
    if not has_column("accounts", "owner"):
        op.add_column(
            "accounts", sa.Column("owner", sa.String(length=32), nullable=True)
        )


def downgrade() -> None:
    op.drop_column("accounts", "owner")
    op.drop_column("accounts", "kind")
