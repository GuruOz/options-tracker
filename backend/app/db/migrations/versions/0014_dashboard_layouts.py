"""home-dashboard widget layouts

One row per scope ('all' or an owner slug) holding the saved widget grid layout
for the customizable home dashboard. Guarded with has_table so a fresh database
(baseline create_all) doesn't collide.

Revision ID: 0014_dashboard_layouts
Revises: 0013_external_statements
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.migration_utils import has_table


revision: str = "0014_dashboard_layouts"
down_revision: Union[str, None] = "0013_external_statements"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if has_table("dashboard_layouts"):
        return
    op.create_table(
        "dashboard_layouts",
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("layout", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("scope"),
    )


def downgrade() -> None:
    op.drop_table("dashboard_layouts")
