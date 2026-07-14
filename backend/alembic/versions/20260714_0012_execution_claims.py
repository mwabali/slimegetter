"""Add durable demo execution idempotency claims."""
from alembic import op
import sqlalchemy as sa

revision = "20260714_0012"
down_revision = "20260714_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="CLAIMED"),
        sa.Column("broker_ticket", sa.String(64)),
        sa.Column("error_type", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_execution_attempts_proposal_id", "execution_attempts", ["proposal_id"], unique=True)
    op.create_index("ix_execution_attempts_correlation_id", "execution_attempts", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_attempts_correlation_id", table_name="execution_attempts")
    op.drop_index("ix_execution_attempts_proposal_id", table_name="execution_attempts")
    op.drop_table("execution_attempts")
