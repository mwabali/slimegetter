from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TradingPermission(StrEnum):
    ALLOW = "ALLOW"
    WAIT = "WAIT"


class SimilarMarketPerformance(BaseModel):
    """Read-only evidence from previously closed trades in similar conditions."""

    model_config = ConfigDict(frozen=True)

    sample_size: int = Field(default=0, ge=0)
    win_rate: Decimal | None = Field(default=None, ge=0, le=1)
    average_reward_risk: Decimal | None = None
    net_pnl: Decimal = Decimal("0")
    similarity_basis: str = "SESSION"


class MikasaAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    permission: TradingPermission
    legacy_permission: TradingPermission = TradingPermission.WAIT
    advisory_mode: str = "CONTINUOUS_MARKET_INTELLIGENCE"
    quality_score: Decimal = Field(ge=0, le=10)
    regime: str
    score_components: dict[str, Decimal] = Field(default_factory=dict)
    calibration_status: str = "UNCALIBRATED"
    similar_market_performance: SimilarMarketPerformance = Field(default_factory=SimilarMarketPerformance)
    minimum_quality_required: Decimal = Decimal("7.00")
    observation_override_active: bool = False
    confidence_multiplier: Decimal = Field(default=Decimal("1.00"), ge=Decimal("0.50"), le=Decimal("1.25"))
    risk_multiplier: Decimal = Field(default=Decimal("1.00"), ge=Decimal("0.50"), le=Decimal("1.15"))
    hard_blocked: bool = False
    reasons: tuple[str, ...] = Field(min_length=1)
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
