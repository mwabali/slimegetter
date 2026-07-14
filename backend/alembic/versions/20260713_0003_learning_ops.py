"""Learning and operations records."""
from alembic import op
import sqlalchemy as sa
revision="20260713_0003"; down_revision="20260713_0002"; branch_labels=None; depends_on=None
def upgrade() -> None:
    for name, columns in {"closed_trades":[sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("strategy_version",sa.String(64),nullable=False),sa.Column("session",sa.String(32),nullable=False),sa.Column("pnl",sa.Numeric(16,2),nullable=False),sa.Column("reward_risk",sa.Numeric(8,4),nullable=False),sa.Column("closed_at",sa.DateTime(timezone=True),server_default=sa.func.now())],"experiments":[sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("name",sa.String(255),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("proposal_json",sa.Text(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now())],"alerts":[sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("severity",sa.String(16),nullable=False),sa.Column("message",sa.Text(),nullable=False),sa.Column("resolved_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now())]}.items(): op.create_table(name,*columns)
def downgrade() -> None:
    op.drop_table("alerts"); op.drop_table("experiments"); op.drop_table("closed_trades")
