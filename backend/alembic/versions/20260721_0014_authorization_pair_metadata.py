"""Add execution authorization evidence and Avenger pair lifecycle metadata."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0014"
down_revision = "20260718_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mt5_fills", sa.Column("strategy_mode", sa.String(32), nullable=True))
    op.add_column("mt5_fills", sa.Column("pair_id", sa.String(64), nullable=True))
    op.create_index("ix_mt5_fills_strategy_mode", "mt5_fills", ["strategy_mode"])
    op.create_index("ix_mt5_fills_pair_id", "mt5_fills", ["pair_id"])
    op.add_column("closed_trades", sa.Column("strategy_mode", sa.String(32), nullable=True))
    op.create_index("ix_closed_trades_strategy_mode", "closed_trades", ["strategy_mode"])
    op.add_column("execution_attempts", sa.Column("pair_id", sa.String(64), nullable=True))
    op.create_index("ix_execution_attempts_pair_id", "execution_attempts", ["pair_id"])
    op.create_table(
        "pair_lifecycles",
        sa.Column("pair_id", sa.String(64), primary_key=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("strategy_mode", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("buy_ticket", sa.String(64), nullable=True),
        sa.Column("sell_ticket", sa.String(64), nullable=True),
        sa.Column("reconciliation_outcome", sa.String(32), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pair_lifecycles_correlation_id", "pair_lifecycles", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_pair_lifecycles_correlation_id", table_name="pair_lifecycles")
    op.drop_table("pair_lifecycles")
    op.drop_index("ix_closed_trades_strategy_mode", table_name="closed_trades")
    op.drop_column("closed_trades", "strategy_mode")
    op.drop_index("ix_execution_attempts_pair_id", table_name="execution_attempts")
    op.drop_column("execution_attempts", "pair_id")
    op.drop_index("ix_mt5_fills_pair_id", table_name="mt5_fills")
    op.drop_index("ix_mt5_fills_strategy_mode", table_name="mt5_fills")
    op.drop_column("mt5_fills", "pair_id")
    op.drop_column("mt5_fills", "strategy_mode")
