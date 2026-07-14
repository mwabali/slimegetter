"""Add a paper-only simulated position ledger."""
from alembic import op
import sqlalchemy as sa

revision = "20260714_0011"
down_revision = "20260713_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulated_positions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False, server_default="XAUUSD"),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("volume", sa.Numeric(16, 4), nullable=False, server_default="1"),
        sa.Column("entry_price", sa.Numeric(16, 5), nullable=False),
        sa.Column("stop_loss", sa.Numeric(16, 5), nullable=False),
        sa.Column("take_profit", sa.Numeric(16, 5), nullable=False),
        sa.Column("exit_price", sa.Numeric(16, 5)),
        sa.Column("pnl", sa.Numeric(16, 5)),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("close_reason", sa.String(32)),
        sa.Column("opened_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_simulated_positions_correlation_id", "simulated_positions", ["correlation_id"], unique=True)
    op.create_index("ix_simulated_positions_status_opened", "simulated_positions", ["status", "opened_at"])


def downgrade() -> None:
    op.drop_index("ix_simulated_positions_status_opened", table_name="simulated_positions")
    op.drop_index("ix_simulated_positions_correlation_id", table_name="simulated_positions")
    op.drop_table("simulated_positions")
