"""Persist shadow worker health."""
from alembic import op
import sqlalchemy as sa
revision="20260713_0005"; down_revision="20260713_0004"; branch_labels=None; depends_on=None
def upgrade() -> None:
    op.create_table("worker_heartbeats", sa.Column("id",sa.Uuid(),primary_key=True), sa.Column("worker_name",sa.String(64),nullable=False), sa.Column("status",sa.String(32),nullable=False), sa.Column("message",sa.Text(),nullable=False), sa.Column("last_seen_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_index("ix_worker_heartbeats_worker_name", "worker_heartbeats", ["worker_name"])
    op.create_index("ix_worker_heartbeats_last_seen_at", "worker_heartbeats", ["last_seen_at"])
def downgrade() -> None:
    op.drop_table("worker_heartbeats")
