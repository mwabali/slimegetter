from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TradeProposalRecord(Base):
    __tablename__ = "trade_proposals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CREATED")
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DecisionEventRecord(Base):
    __tablename__ = "decision_events"
    __table_args__ = (UniqueConstraint("correlation_id", "event_sequence"), Index("ix_decision_events_dashboard", "created_at", "agent_name", "event_type"))

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    event_sequence: Mapped[int] = mapped_column(nullable=False)
    proposal_id: Mapped[UUID | None] = mapped_column(ForeignKey("trade_proposals.id"))
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClosedTradeRecord(Base):
    __tablename__ = "closed_trades"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    session: Mapped[str] = mapped_column(String(32), nullable=False)
    pnl: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    reward_risk: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    source_deal_ticket: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Numeric(16, 2))
    max_adverse_excursion: Mapped[float | None] = mapped_column(Numeric(16, 2))
    profit_giveback: Mapped[float | None] = mapped_column(Numeric(16, 2))
    exit_reason: Mapped[str | None] = mapped_column(String(64))
    initial_risk_usd: Mapped[float | None] = mapped_column(Numeric(16, 2))
    exit_r: Mapped[float | None] = mapped_column(Numeric(12, 4))
    peak_r: Mapped[float | None] = mapped_column(Numeric(12, 4))
    exit_policy_version: Mapped[str | None] = mapped_column(String(64))
    normal_volume: Mapped[float | None] = mapped_column(Numeric(16, 4))
    approved_volume: Mapped[float | None] = mapped_column(Numeric(16, 4))
    risk_multiplier: Mapped[float | None] = mapped_column(Numeric(8, 4))
    risk_state: Mapped[str | None] = mapped_column(String(16))
    risk_state_reason: Mapped[str | None] = mapped_column(Text)
    adaptive_recommended_volume: Mapped[float | None] = mapped_column(Numeric(16, 4))
    adaptive_sizing_mode: Mapped[str | None] = mapped_column(String(16))
    estimated_counterfactual_pnl: Mapped[float | None] = mapped_column(Numeric(16, 2))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExperimentRecord(Base):
    __tablename__ = "experiments"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PROPOSED")
    proposal_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertRecord(Base):
    __tablename__ = "alerts"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExecutionIncidentRecord(Base):
    __tablename__ = "execution_incidents"
    __table_args__ = (Index("ix_execution_incidents_unresolved", "severity", "resolved_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    incident_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    position_ticket: Mapped[str | None] = mapped_column(String(64), index=True)
    correlation_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128))
    resolution_note: Mapped[str | None] = mapped_column(Text)


class WorkerHeartbeatRecord(Base):
    __tablename__ = "worker_heartbeats"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    worker_name: Mapped[str] = mapped_column(String(64), index=True, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PositionRecord(Base):
    __tablename__ = "mt5_positions"
    ticket: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False)
    price_open: Mapped[float] = mapped_column(Numeric(16, 5), nullable=False)
    stop_loss: Mapped[float | None] = mapped_column(Numeric(16, 5))
    take_profit: Mapped[float | None] = mapped_column(Numeric(16, 5))
    profit: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class FillRecord(Base):
    __tablename__ = "mt5_fills"
    deal_ticket: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_ticket: Mapped[str | None] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(16, 5), nullable=False)
    profit: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry: Mapped[str] = mapped_column(String(16), nullable=False, default="IN")
    position_ticket: Mapped[str | None] = mapped_column(String(64), index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class StrategyRecord(Base):
    __tablename__ = "strategies"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    promotion_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchProposalRecord(Base):
    __tablename__ = "research_proposals"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PROPOSED")
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SimulatedPositionRecord(Base):
    """Paper-only lifecycle; this table has no MT5 ticket or execution path."""
    __tablename__ = "simulated_positions"
    __table_args__ = (Index("ix_simulated_positions_status_opened", "status", "opened_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, unique=True, index=True, nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, default="XAUUSD")
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    volume: Mapped[float] = mapped_column(Numeric(16, 4), nullable=False, default=1)
    entry_price: Mapped[float] = mapped_column(Numeric(16, 5), nullable=False)
    stop_loss: Mapped[float] = mapped_column(Numeric(16, 5), nullable=False)
    take_profit: Mapped[float] = mapped_column(Numeric(16, 5), nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Numeric(16, 5))
    pnl: Mapped[float | None] = mapped_column(Numeric(16, 5))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    close_reason: Mapped[str | None] = mapped_column(String(32))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecutionAttemptRecord(Base):
    """Durable exactly-once claim at the guarded demo broker boundary."""
    __tablename__ = "execution_attempts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(Uuid, unique=True, index=True, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CLAIMED")
    broker_ticket: Mapped[str | None] = mapped_column(String(64))
    error_type: Mapped[str | None] = mapped_column(String(128))
    entry_price: Mapped[float | None] = mapped_column(Numeric(16, 5))
    initial_stop_loss: Mapped[float | None] = mapped_column(Numeric(16, 5))
    initial_take_profit: Mapped[float | None] = mapped_column(Numeric(16, 5))
    initial_risk_price: Mapped[float | None] = mapped_column(Numeric(16, 5))
    initial_risk_usd: Mapped[float | None] = mapped_column(Numeric(16, 2))
    intended_reward_risk: Mapped[float | None] = mapped_column(Numeric(8, 4))
    volume: Mapped[float | None] = mapped_column(Numeric(16, 4))
    normal_volume: Mapped[float | None] = mapped_column(Numeric(16, 4))
    approved_volume: Mapped[float | None] = mapped_column(Numeric(16, 4))
    risk_multiplier: Mapped[float | None] = mapped_column(Numeric(8, 4))
    risk_state: Mapped[str | None] = mapped_column(String(16))
    risk_state_reason: Mapped[str | None] = mapped_column(Text)
    adaptive_recommended_volume: Mapped[float | None] = mapped_column(Numeric(16, 4))
    adaptive_sizing_mode: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DefensiveRiskStateRecord(Base):
    """Durable XAUUSD demo risk state; restart must not erase defensive posture."""
    __tablename__ = "defensive_risk_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    session_key: Mapped[str] = mapped_column(String(32), nullable=False)
    session_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_risk_state: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_multiplier: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    consecutive_losses: Mapped[int] = mapped_column(nullable=False, default=0)
    hard_stop_count: Mapped[int] = mapped_column(nullable=False, default=0)
    consecutive_hard_stops: Mapped[int] = mapped_column(nullable=False, default=0)
    session_start_balance: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    current_balance: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    session_realized_pnl: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    session_drawdown_usd: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    session_drawdown_pct: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    peak_session_equity: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    current_equity: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False)
    equity_drawdown_usd: Mapped[float] = mapped_column(Numeric(16, 2), nullable=False, default=0)
    equity_drawdown_pct: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    recent_average_loss: Mapped[float | None] = mapped_column(Numeric(16, 2))
    recent_average_win: Mapped[float | None] = mapped_column(Numeric(16, 2))
    recent_profit_factor: Mapped[float | None] = mapped_column(Numeric(12, 4))
    recovery_wins: Mapped[int] = mapped_column(nullable=False, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_reason: Mapped[str] = mapped_column(Text, nullable=False)
    state_entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
