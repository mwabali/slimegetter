"""Use SQLAlchemy's canonical unique worker-name index."""
from alembic import op

revision = "20260713_0010"
down_revision = "20260713_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_worker_heartbeats_worker_name", table_name="worker_heartbeats")
    op.drop_index("ix_worker_heartbeats_worker_name", table_name="worker_heartbeats")
    op.create_index("ix_worker_heartbeats_worker_name", "worker_heartbeats", ["worker_name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_worker_heartbeats_worker_name", table_name="worker_heartbeats")
    op.create_index("ix_worker_heartbeats_worker_name", "worker_heartbeats", ["worker_name"])
