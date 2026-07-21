"""Add persistent defensive risk sizing and journal evidence."""
from alembic import op
import sqlalchemy as sa


revision = "20260722_0017"
down_revision = "20260721_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "defensive_risk_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_key", sa.String(32), nullable=False),
        sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_risk_state", sa.String(16), nullable=False),
        sa.Column("risk_multiplier", sa.Numeric(8, 4), nullable=False),
        sa.Column("consecutive_losses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hard_stop_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consecutive_hard_stops", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("session_start_balance", sa.Numeric(16, 2), nullable=False),
        sa.Column("current_balance", sa.Numeric(16, 2), nullable=False),
        sa.Column("session_realized_pnl", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("session_drawdown_usd", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("session_drawdown_pct", sa.Numeric(8, 4), nullable=False, server_default="0"),
        sa.Column("peak_session_equity", sa.Numeric(16, 2), nullable=False),
        sa.Column("current_equity", sa.Numeric(16, 2), nullable=False),
        sa.Column("equity_drawdown_usd", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("equity_drawdown_pct", sa.Numeric(8, 4), nullable=False, server_default="0"),
        sa.Column("recent_average_loss", sa.Numeric(16, 2)),
        sa.Column("recent_average_win", sa.Numeric(16, 2)),
        sa.Column("recent_profit_factor", sa.Numeric(12, 4)),
        sa.Column("recovery_wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column("state_reason", sa.Text(), nullable=False),
        sa.Column("state_entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        sa.Column("normal_volume", sa.Numeric(16, 4)),
        sa.Column("approved_volume", sa.Numeric(16, 4)),
        sa.Column("risk_multiplier", sa.Numeric(8, 4)),
        sa.Column("risk_state", sa.String(16)),
        sa.Column("risk_state_reason", sa.Text()),
        sa.Column("adaptive_recommended_volume", sa.Numeric(16, 4)),
        sa.Column("adaptive_sizing_mode", sa.String(16)),
    ):
        op.add_column("execution_attempts", column)
    for column in (
        sa.Column("normal_volume", sa.Numeric(16, 4)),
        sa.Column("approved_volume", sa.Numeric(16, 4)),
        sa.Column("risk_multiplier", sa.Numeric(8, 4)),
        sa.Column("risk_state", sa.String(16)),
        sa.Column("risk_state_reason", sa.Text()),
        sa.Column("adaptive_recommended_volume", sa.Numeric(16, 4)),
        sa.Column("adaptive_sizing_mode", sa.String(16)),
        sa.Column("estimated_counterfactual_pnl", sa.Numeric(16, 2)),
    ):
        op.add_column("closed_trades", column)
    op.add_column("mt5_fills", sa.Column("position_ticket", sa.String(64)))
    op.create_index("ix_mt5_fills_position_ticket", "mt5_fills", ["position_ticket"])


def downgrade() -> None:
    op.drop_index("ix_mt5_fills_position_ticket", table_name="mt5_fills")
    op.drop_column("mt5_fills", "position_ticket")
    for name in (
        "estimated_counterfactual_pnl", "adaptive_sizing_mode", "adaptive_recommended_volume",
        "risk_state_reason", "risk_state", "risk_multiplier", "approved_volume", "normal_volume",
    ):
        op.drop_column("closed_trades", name)
    for name in (
        "adaptive_sizing_mode", "adaptive_recommended_volume", "risk_state_reason", "risk_state",
        "risk_multiplier", "approved_volume", "normal_volume",
    ):
        op.drop_column("execution_attempts", name)
    op.drop_table("defensive_risk_state")
