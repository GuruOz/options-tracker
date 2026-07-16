"""per-account settings (watchlist + alert thresholds)

Splits the per-user half of the single global settings row out into one row per
account, so each user curates their own tracked underlyings and tunes their own
alert thresholds. Signal weights, the BS rate and the risk beta map stay global —
they drive the conid-keyed market data every account shares.

Existing accounts inherit the current global watchlist/thresholds, so a
single-user deployment sees no change.

Revision ID: 0009_account_settings
Revises: 0008_chain_cycle_credits
Create Date: 2026-07-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.migration_utils import has_table


revision: str = "0009_account_settings"
down_revision: Union[str, None] = "0008_chain_cycle_credits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if has_table("account_settings"):
        return  # baseline create_all already made it (fresh database)
    op.create_table(
        "account_settings",
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.account_id"]),
        sa.PrimaryKeyConstraint("account_id"),
    )

    # Seed every existing account from the global row so the current user's
    # watchlist and thresholds survive the split untouched. COALESCE covers a
    # settings row written before either key existed.
    op.execute(
        """
        INSERT INTO account_settings (account_id, data)
        SELECT
            a.account_id,
            jsonb_build_object(
                'underlyings', COALESCE(s.data -> 'underlyings', '[]'::jsonb),
                'alerts', COALESCE(s.data -> 'alerts', '{}'::jsonb)
            )
        FROM accounts a
        CROSS JOIN (SELECT data FROM settings WHERE id = 1) s
        ON CONFLICT (account_id) DO NOTHING
        """
    )
    # The global row keeps its now-unused 'underlyings'/'alerts' keys: harmless
    # to the readers (which no longer look at them) and it makes the downgrade
    # lossless.


def downgrade() -> None:
    op.drop_table("account_settings")
