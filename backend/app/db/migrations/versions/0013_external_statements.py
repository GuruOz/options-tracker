"""CPF/Endowus statement-upload tables

Adds the four tables that back statement ingestion:
  * statement_uploads  — one row per uploaded PDF (unique file_sha256 for dedupe)
  * external_balances  — CPF sub-account + Endowus goal balance snapshots
  * cpf_transactions   — the CPF ledger rows (deduped by row_hash)
  * external_holdings  — Endowus per-fund snapshots

On a fresh database the baseline create_all already built these from the models,
so each create is guarded with has_table (matching 0009's pattern).

Revision ID: 0013_external_statements
Revises: 0012_account_kind_owner
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.migration_utils import has_table


revision: str = "0013_external_statements"
down_revision: Union[str, None] = "0012_account_kind_owner"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MONEY = sa.Numeric(20, 6)


def upgrade() -> None:
    if not has_table("statement_uploads"):
        op.create_table(
            "statement_uploads",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("account_id", sa.String(length=32), nullable=False),
            sa.Column("source", sa.String(length=16), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=True),
            sa.Column("period_end", sa.Date(), nullable=True),
            sa.Column("filename", sa.String(length=256), nullable=True),
            sa.Column("file_sha256", sa.String(length=64), nullable=False),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("file_sha256", name="uq_statement_sha"),
        )
        op.create_index("ix_statement_uploads_account_id", "statement_uploads", ["account_id"])
        op.create_index("ix_statement_uploads_file_sha256", "statement_uploads", ["file_sha256"])

    if not has_table("external_balances"):
        op.create_table(
            "external_balances",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("account_id", sa.String(length=32), nullable=False),
            sa.Column("as_of", sa.Date(), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=False),
            sa.Column("balance", _MONEY, nullable=True),
            sa.Column("currency", sa.String(length=8), server_default="SGD", nullable=False),
            sa.Column("upload_id", sa.BigInteger(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
            sa.ForeignKeyConstraint(["upload_id"], ["statement_uploads.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("account_id", "as_of", "category", name="uq_ext_bal"),
        )
        op.create_index("ix_external_balances_account_id", "external_balances", ["account_id"])
        op.create_index("ix_ext_bal_account_asof", "external_balances", ["account_id", "as_of"])

    if not has_table("cpf_transactions"):
        op.create_table(
            "cpf_transactions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("account_id", sa.String(length=32), nullable=False),
            sa.Column("txn_date", sa.Date(), nullable=False),
            sa.Column("code", sa.String(length=8), nullable=False),
            sa.Column("for_month", sa.Date(), nullable=True),
            sa.Column("ref", sa.String(length=8), nullable=True),
            sa.Column("oa_amount", _MONEY, nullable=True),
            sa.Column("sa_amount", _MONEY, nullable=True),
            sa.Column("ma_amount", _MONEY, nullable=True),
            sa.Column("upload_id", sa.BigInteger(), nullable=True),
            sa.Column("row_hash", sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
            sa.ForeignKeyConstraint(["upload_id"], ["statement_uploads.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("account_id", "row_hash", name="uq_cpf_txn"),
        )
        op.create_index("ix_cpf_transactions_account_id", "cpf_transactions", ["account_id"])
        op.create_index("ix_cpf_txn_account_date", "cpf_transactions", ["account_id", "txn_date"])

    if not has_table("external_holdings"):
        op.create_table(
            "external_holdings",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("account_id", sa.String(length=32), nullable=False),
            sa.Column("as_of", sa.Date(), nullable=False),
            sa.Column("goal_name", sa.String(length=128), nullable=True),
            sa.Column("fund_name", sa.String(length=256), nullable=True),
            sa.Column("asset_class", sa.String(length=64), nullable=True),
            sa.Column("funding_source", sa.String(length=32), nullable=True),
            sa.Column("units", _MONEY, nullable=True),
            sa.Column("nav", _MONEY, nullable=True),
            sa.Column("avg_price", _MONEY, nullable=True),
            sa.Column("market_value", _MONEY, nullable=True),
            sa.Column("allocation_pct", _MONEY, nullable=True),
            sa.Column("currency", sa.String(length=8), server_default="SGD", nullable=False),
            sa.Column("upload_id", sa.BigInteger(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
            sa.ForeignKeyConstraint(["upload_id"], ["statement_uploads.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "account_id", "as_of", "goal_name", "fund_name", "funding_source",
                name="uq_ext_holding",
            ),
        )
        op.create_index("ix_external_holdings_account_id", "external_holdings", ["account_id"])
        op.create_index("ix_ext_holding_account_asof", "external_holdings", ["account_id", "as_of"])


def downgrade() -> None:
    op.drop_table("external_holdings")
    op.drop_table("cpf_transactions")
    op.drop_table("external_balances")
    op.drop_table("statement_uploads")
