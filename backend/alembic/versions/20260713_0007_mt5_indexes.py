"""Align MT5 fill indexes with ORM query paths."""
from alembic import op

revision = "20260713_0007"
down_revision = "20260713_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_mt5_fills_filled_at", table_name="mt5_fills")
    op.create_index("ix_mt5_fills_order_ticket", "mt5_fills", ["order_ticket"])
    op.create_index("ix_mt5_fills_synced_at", "mt5_fills", ["synced_at"])


def downgrade() -> None:
    op.drop_index("ix_mt5_fills_synced_at", table_name="mt5_fills")
    op.drop_index("ix_mt5_fills_order_ticket", table_name="mt5_fills")
    op.create_index("ix_mt5_fills_filled_at", "mt5_fills", ["filled_at"])
