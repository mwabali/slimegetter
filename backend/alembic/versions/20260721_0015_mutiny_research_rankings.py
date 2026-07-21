"""Persist isolated research rankings for Mutiny helpers."""

from alembic import op
import sqlalchemy as sa

revision = "20260721_0015"
down_revision = "20260721_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_rankings",
        sa.Column("strategy_version", sa.String(64), primary_key=True),
        sa.Column("pool", sa.String(16), nullable=False, server_default="CORE"),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_outcomes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("expectancy", sa.Numeric(16, 6), nullable=True),
        sa.Column("profit_factor", sa.Numeric(16, 6), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="OBSERVED"),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_strategy_rankings_computed_at", "strategy_rankings", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_strategy_rankings_computed_at", table_name="strategy_rankings")
    op.drop_table("strategy_rankings")
