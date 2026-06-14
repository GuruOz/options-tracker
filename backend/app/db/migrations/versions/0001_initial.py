"""initial schema

Creates the full schema directly from the SQLAlchemy metadata so this baseline
migration can never drift from the models. Subsequent changes use normal
``alembic revision --autogenerate`` migrations.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-14
"""
from alembic import op

from app.db.base import Base
import app.db.models  # noqa: F401  (registers all tables on Base.metadata)

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
