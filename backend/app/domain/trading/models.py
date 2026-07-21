from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class ProposalStatus(StrEnum):
    CREATED = "CREATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TradeLifecycleStatus(StrEnum):
    CREATED = "CREATED"
    ANALYZED = "ANALYZED"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


_TRANSITIONS: dict[TradeLifecycleStatus, frozenset[TradeLifecycleStatus]] = {
    TradeLifecycleStatus.CREATED: frozenset({TradeLifecycleStatus.ANALYZED}),
    TradeLifecycleStatus.ANALYZED: frozenset({TradeLifecycleStatus.PROPOSED}),
    TradeLifecycleStatus.PROPOSED: frozenset({TradeLifecycleStatus.APPROVED, TradeLifecycleStatus.REJECTED}),
    TradeLifecycleStatus.APPROVED: frozenset({TradeLifecycleStatus.SUBMITTED, TradeLifecycleStatus.CANCELLED}),
    TradeLifecycleStatus.REJECTED: frozenset(),
    TradeLifecycleStatus.SUBMITTED: frozenset({TradeLifecycleStatus.FILLED, TradeLifecycleStatus.CANCELLED}),
    TradeLifecycleStatus.FILLED: frozenset({TradeLifecycleStatus.CLOSED}),
    TradeLifecycleStatus.CANCELLED: frozenset(),
    TradeLifecycleStatus.CLOSED: frozenset(),
}


def validate_transition(current: TradeLifecycleStatus, target: TradeLifecycleStatus) -> None:
    """Fail closed when a caller attempts to skip the audited trade state machine."""
    if target not in _TRANSITIONS[current]:
        raise ValueError(f"Invalid trade state transition: {current} -> {target}")


class AccountSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    account_id: str
    balance: Decimal | None = None
    equity: Decimal = Field(gt=0)
    free_margin: Decimal = Field(ge=0)
    used_margin: Decimal | None = None
    margin_level: Decimal | None = None
    floating_pnl: Decimal | None = None
    currency: str | None = None
    leverage: int | None = None
    open_position_count: int = Field(ge=0)
    current_exposure_pct: Decimal = Field(ge=0)
    realized_daily_pnl: Decimal
    realized_weekly_pnl: Decimal


class RiskProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    risk_per_trade_pct: Decimal = Field(gt=0, le=5)
    max_daily_loss_pct: Decimal = Field(gt=0, le=20)
    max_weekly_loss_pct: Decimal = Field(gt=0, le=40)
    max_spread: Decimal = Field(gt=0)
    max_exposure_pct: Decimal = Field(gt=0, le=100)
    max_simultaneous_trades: int = Field(gt=0, le=100)
    min_reward_risk: Decimal = Field(gt=0)
    allowed_sessions: frozenset[str] = frozenset({"LONDON", "NEW_YORK"})


class TradeProposal(BaseModel):
    """A structured Eren output. This object has no execution capability."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    correlation_id: UUID = Field(default_factory=uuid4)
    symbol: str = "XAUUSD"
    side: Side
    volume: Decimal = Field(gt=0)
    entry_price: Decimal = Field(gt=0)
    stop_loss: Decimal = Field(gt=0)
    take_profit: Decimal = Field(gt=0)
    confidence: Decimal = Field(ge=0, le=1)
    reasons: tuple[str, ...] = Field(min_length=1)
    indicators_used: tuple[str, ...] = Field(min_length=1)
    expected_risk_pct: Decimal = Field(gt=0, le=5)
    session: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("symbol")
    @classmethod
    def xauusd_only(cls, value: str) -> str:
        if value.upper() != "XAUUSD":
            raise ValueError("The initial release permits XAUUSD only")
        return value.upper()

    def reward_risk_ratio(self) -> Decimal:
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return reward / risk if risk else Decimal("0")


class RiskDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    proposal_id: UUID
    correlation_id: UUID
    status: ProposalStatus
    reasons: tuple[str, ...]
    risk_posture: str = "CALCULATED"
    recommended_size_multiplier: Decimal = Field(default=Decimal("1.00"), gt=0, le=1)
    accepted_warnings: tuple[str, ...] = ()
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SymbolSpecification(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str = "XAUUSD"
    point: Decimal = Field(gt=0)
    volume_min: Decimal = Field(gt=0)
    volume_max: Decimal = Field(gt=0)
    volume_step: Decimal = Field(gt=0)
    volume_limit: Decimal | None = Field(default=None, gt=0)
    trade_contract_size: Decimal = Field(gt=0)


class PositionSizeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    volume: Decimal = Field(gt=0)
    risk_amount: Decimal = Field(gt=0)
    stop_distance: Decimal = Field(gt=0)
