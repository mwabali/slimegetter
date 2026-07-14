"""Link broker deals to persisted closed-trade evidence."""
from alembic import op
import sqlalchemy as sa

revision = "20260713_0008"
down_revision = "20260713_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("closed_trades") as batch:
        batch.add_column(sa.Column("source_deal_ticket", sa.String(64)))
        batch.create_index("ix_closed_trades_source_deal_ticket", ["source_deal_ticket"], unique=True)
    with op.batch_alter_table("mt5_fills") as batch:
        batch.add_column(sa.Column("entry", sa.String(16), nullable=False, server_default="IN"))


def downgrade() -> None:
    with op.batch_alter_table("mt5_fills") as batch:
        batch.drop_column("entry")
    with op.batch_alter_table("closed_trades") as batch:
        batch.drop_index("ix_closed_trades_source_deal_ticket")
        batch.drop_column("source_deal_ticket")
