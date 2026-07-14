"""Keep one authoritative heartbeat row per worker."""
from alembic import op

revision = "20260713_0009"
down_revision = "20260713_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM worker_heartbeats WHERE id NOT IN (SELECT MAX(id) FROM worker_heartbeats GROUP BY worker_name)")
    op.create_index("uq_worker_heartbeats_worker_name", "worker_heartbeats", ["worker_name"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_worker_heartbeats_worker_name", table_name="worker_heartbeats")
