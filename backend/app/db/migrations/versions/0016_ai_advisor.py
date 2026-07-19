"""AI advisor config + suggestions

Adds:
  * ai_config      — single-row BYO-key config (encrypted key, never returned)
  * ai_suggestions — generated suggestion history with the anonymized input blob

Guarded with has_table so a fresh database (baseline create_all) doesn't collide.

Revision ID: 0016_ai_advisor
Revises: 0015_planning
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.migration_utils import has_table


revision: str = "0016_ai_advisor"
down_revision: Union[str, None] = "0015_planning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if not has_table("ai_config"):
        op.create_table(
            "ai_config",
            sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
            sa.Column("provider", sa.String(length=16), nullable=True),
            sa.Column("base_url", sa.String(length=256), nullable=True),
            sa.Column("model", sa.String(length=64), nullable=True),
            sa.Column("api_key_encrypted", sa.LargeBinary(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if not has_table("ai_suggestions"):
        op.create_table(
            "ai_suggestions",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("owner", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("provider", sa.String(length=16), nullable=True),
            sa.Column("model", sa.String(length=64), nullable=True),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("input_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ai_suggestions_owner", "ai_suggestions", ["owner"])


def downgrade() -> None:
    op.drop_table("ai_suggestions")
    op.drop_table("ai_config")
