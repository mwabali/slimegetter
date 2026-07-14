"""Dashboard journal read indexes."""
from alembic import op

revision = "20260713_0004"
down_revision = "20260713_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_decision_events_dashboard", "decision_events", ["created_at", "agent_name", "event_type"])


def downgrade() -> None:
    op.drop_index("ix_decision_events_dashboard", table_name="decision_events")
