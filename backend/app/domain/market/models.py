from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MarketSession(StrEnum):
    ASIA = "ASIA"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    OFF_HOURS = "OFF_HOURS"


class EventImpact(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MarketSnapshot(BaseModel):
    """A point-in-time input supplied by a market-data adapter, never an agent."""

    model_config = ConfigDict(frozen=True)

    symbol: str = "XAUUSD"
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)
    atr: Decimal = Field(gt=0, description="ATR expressed in price units")
    ema_fast: Decimal = Field(gt=0)
    ema_slow: Decimal = Field(gt=0)
    rsi: Decimal = Field(ge=0, le=100)
    trend_strength: Decimal = Field(ge=0, le=10)
    volatility_score: Decimal = Field(ge=0, le=10)
    liquidity_score: Decimal = Field(ge=0, le=10)
    momentum_score: Decimal = Field(ge=0, le=10)
    session: MarketSession

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def midpoint(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")


class EconomicEvent(BaseModel):
    """Normalized external event. Source traceability is mandatory."""

    model_config = ConfigDict(frozen=True)

    title: str = Field(min_length=1, max_length=255)
    impact: EventImpact
    scheduled_at: datetime
    source: str = Field(min_length=1, max_length=255)
    source_url: str | None = None
    is_gold_relevant: bool = True

    @field_validator("scheduled_at")
    @classmethod
    def must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone")
        return value
