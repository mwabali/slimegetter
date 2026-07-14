"""Add deterministic event ordering to correlated decision timelines."""

from alembic import op
import sqlalchemy as sa

revision = "20260713_0002"
down_revision = "20260713_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("decision_events") as batch_op:
        batch_op.add_column(sa.Column("event_sequence", sa.Integer(), nullable=False, server_default="0"))
        batch_op.create_unique_constraint(
            "uq_decision_events_correlation_sequence", ["correlation_id", "event_sequence"]
        )


def downgrade() -> None:
    with op.batch_alter_table("decision_events") as batch_op:
        batch_op.drop_constraint("uq_decision_events_correlation_sequence", type_="unique")
        batch_op.drop_column("event_sequence")
