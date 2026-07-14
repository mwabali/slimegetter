"""Initial immutable trade proposal and decision journal tables."""

from alembic import op
import sqlalchemy as sa

revision = "20260713_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_proposals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_trade_proposals_correlation_id", "trade_proposals", ["correlation_id"])
    op.create_table(
        "decision_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), sa.ForeignKey("trade_proposals.id")),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_decision_events_correlation_id", "decision_events", ["correlation_id"])


def downgrade() -> None:
    op.drop_table("decision_events")
    op.drop_table("trade_proposals")
