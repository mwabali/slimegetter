"""Persist read-only MT5 state, strategy versions, and Levi proposals."""
from alembic import op
import sqlalchemy as sa

revision = "20260713_0006"
down_revision = "20260713_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mt5_positions",
        sa.Column("ticket", sa.String(64), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("volume", sa.Numeric(16, 4), nullable=False),
        sa.Column("price_open", sa.Numeric(16, 5), nullable=False),
        sa.Column("stop_loss", sa.Numeric(16, 5)),
        sa.Column("take_profit", sa.Numeric(16, 5)),
        sa.Column("profit", sa.Numeric(16, 2), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mt5_positions_symbol", "mt5_positions", ["symbol"])
    op.create_index("ix_mt5_positions_synced_at", "mt5_positions", ["synced_at"])
    op.create_table(
        "mt5_fills",
        sa.Column("deal_ticket", sa.String(64), primary_key=True),
        sa.Column("order_ticket", sa.String(64)),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("volume", sa.Numeric(16, 4), nullable=False),
        sa.Column("price", sa.Numeric(16, 5), nullable=False),
        sa.Column("profit", sa.Numeric(16, 2), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mt5_fills_symbol", "mt5_fills", ["symbol"])
    op.create_index("ix_mt5_fills_filled_at", "mt5_fills", ["filled_at"])
    op.create_table(
        "strategies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("promotion_notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("promoted_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "research_proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("citations_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("research_proposals")
    op.drop_table("strategies")
    op.drop_table("mt5_fills")
    op.drop_table("mt5_positions")
