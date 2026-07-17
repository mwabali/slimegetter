"""Add execution incidents and exit evidence fields."""
from alembic import op
import sqlalchemy as sa

revision = "20260718_0013"
down_revision = "20260714_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_incidents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("incident_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("position_ticket", sa.String(64)),
        sa.Column("correlation_id", sa.Uuid()),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.String(128)),
        sa.Column("resolution_note", sa.Text()),
    )
    op.create_index("ix_execution_incidents_incident_type", "execution_incidents", ["incident_type"])
    op.create_index("ix_execution_incidents_severity", "execution_incidents", ["severity"])
    op.create_index("ix_execution_incidents_position_ticket", "execution_incidents", ["position_ticket"])
    op.create_index("ix_execution_incidents_correlation_id", "execution_incidents", ["correlation_id"])
    op.create_index("ix_execution_incidents_resolved_at", "execution_incidents", ["resolved_at"])
    op.create_index("ix_execution_incidents_unresolved", "execution_incidents", ["severity", "resolved_at"])
    for column in (
        sa.Column("entry_price", sa.Numeric(16, 5)),
        sa.Column("initial_stop_loss", sa.Numeric(16, 5)),
        sa.Column("initial_take_profit", sa.Numeric(16, 5)),
        sa.Column("initial_risk_price", sa.Numeric(16, 5)),
        sa.Column("initial_risk_usd", sa.Numeric(16, 2)),
        sa.Column("intended_reward_risk", sa.Numeric(8, 4)),
        sa.Column("volume", sa.Numeric(16, 4)),
    ):
        op.add_column("execution_attempts", column)
    for column in (
        sa.Column("max_favorable_excursion", sa.Numeric(16, 2)),
        sa.Column("max_adverse_excursion", sa.Numeric(16, 2)),
        sa.Column("profit_giveback", sa.Numeric(16, 2)),
        sa.Column("exit_reason", sa.String(64)),
        sa.Column("initial_risk_usd", sa.Numeric(16, 2)),
        sa.Column("exit_r", sa.Numeric(12, 4)),
        sa.Column("peak_r", sa.Numeric(12, 4)),
        sa.Column("exit_policy_version", sa.String(64)),
    ):
        op.add_column("closed_trades", column)


def downgrade() -> None:
    for name in (
        "volume",
        "intended_reward_risk",
        "initial_risk_usd",
        "initial_risk_price",
        "initial_take_profit",
        "initial_stop_loss",
        "entry_price",
    ):
        op.drop_column("execution_attempts", name)
    for name in (
        "exit_policy_version",
        "peak_r",
        "exit_r",
        "initial_risk_usd",
        "exit_reason",
        "profit_giveback",
        "max_adverse_excursion",
        "max_favorable_excursion",
    ):
        op.drop_column("closed_trades", name)
    op.drop_index("ix_execution_incidents_unresolved", table_name="execution_incidents")
    op.drop_index("ix_execution_incidents_resolved_at", table_name="execution_incidents")
    op.drop_index("ix_execution_incidents_correlation_id", table_name="execution_incidents")
    op.drop_index("ix_execution_incidents_position_ticket", table_name="execution_incidents")
    op.drop_index("ix_execution_incidents_severity", table_name="execution_incidents")
    op.drop_index("ix_execution_incidents_incident_type", table_name="execution_incidents")
    op.drop_table("execution_incidents")
