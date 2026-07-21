"""Persist read-only local-time profitability observations."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0016"
down_revision = "20260721_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "time_window_rankings",
        sa.Column("window_key", sa.String(32), primary_key=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Africa/Nairobi"),
        sa.Column("hour_start", sa.Integer(), nullable=False),
        sa.Column("hour_end", sa.Integer(), nullable=False),
        sa.Column("sample_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("net_pnl", sa.Numeric(16, 6), nullable=False, server_default="0"),
        sa.Column("expectancy", sa.Numeric(16, 6), nullable=True),
        sa.Column("profit_factor", sa.Numeric(16, 6), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="OBSERVED"),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_time_window_rankings_computed_at", "time_window_rankings", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_time_window_rankings_computed_at", table_name="time_window_rankings")
    op.drop_table("time_window_rankings")
