from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.agents.annie.models import AnnieAssessment, NewsRiskStatus
from app.agents.annie.service import AnnieService
from app.agents.eren.service import ErenService
from app.agents.erwin.service import CommanderErwinService
from app.agents.mikasa.models import MikasaAssessment, SimilarMarketPerformance
from app.agents.mikasa.service import MikasaService
from app.domain.market.models import EconomicEvent, MarketSnapshot
from app.domain.trading.models import AccountSnapshot, RiskDecision, RiskProfile, Side, TradeProposal


class DecisionPreview(BaseModel):
    """Simulation output for the dashboard. It has no execution request field."""

    model_config = ConfigDict(frozen=True)

    annie: AnnieAssessment
    mikasa: MikasaAssessment
    eren: TradeProposal | None
    erwin: RiskDecision | None
    final_message: str
    correlation_id: UUID


class DecisionPreviewRequest(BaseModel):
    """Input for a journaled, non-executing decision simulation."""

    model_config = ConfigDict(frozen=True)

    market: MarketSnapshot
    events: tuple[EconomicEvent, ...] = ()
    source_freshness_minutes: int = Field(default=0, ge=0)
    account: AccountSnapshot
    profile: RiskProfile


class DecisionPreviewWorkflow:
    """Routes independent agent outputs without taking any decision itself."""

    def __init__(self) -> None:
        self._annie = AnnieService()
        self._mikasa = MikasaService()
        self._eren = ErenService()
        self._erwin = CommanderErwinService()

    def run(
        self,
        market: MarketSnapshot,
        events: tuple[EconomicEvent, ...],
        source_freshness_minutes: int,
        account: AccountSnapshot,
        profile: RiskProfile,
        minimum_market_quality: Decimal = Decimal("7.00"),
        observation_override: bool = False,
        similar_market_performance: SimilarMarketPerformance | None = None,
        exploration_trade_when_flat: bool = False,
    ) -> DecisionPreview:
        correlation_id = uuid4()
        annie = self._annie.assess(events, source_freshness_minutes)
        mikasa = self._mikasa.assess(
            market,
            profile.max_spread,
            minimum_market_quality,
            observation_override,
            similar_performance=similar_market_performance,
        )
        if annie.status is not NewsRiskStatus.SAFE:
            return DecisionPreview(annie=annie, mikasa=mikasa, eren=None, erwin=None, correlation_id=correlation_id, final_message="WAIT: Annie flagged information risk")
        try:
            eren = self._eren.generate(market, profile.risk_per_trade_pct, correlation_id)
        except ValueError as exc:
            if exploration_trade_when_flat:
                side = Side.BUY if market.rsi >= Decimal("50") or market.ema_fast >= market.ema_slow else Side.SELL
                entry = market.ask if side is Side.BUY else market.bid
                stop_distance = market.atr
                target_distance = market.atr * Decimal("1.2")
                eren = TradeProposal(
                    correlation_id=correlation_id,
                    side=side,
                    volume=Decimal("0.01"),
                    entry_price=entry,
                    stop_loss=entry - stop_distance if side is Side.BUY else entry + stop_distance,
                    take_profit=entry + target_distance if side is Side.BUY else entry - target_distance,
                    confidence=Decimal("0.51"),
                    reasons=(
                        f"Demo exploration fallback after normal setup returned: {exc}",
                        "Direction chosen from weak EMA/RSI momentum so the demo account can collect execution evidence",
                    ),
                    indicators_used=("EMA", "RSI", "ATR", "DEMO_EXPLORATION"),
                    expected_risk_pct=profile.risk_per_trade_pct,
                    session=market.session.value,
                )
            else:
                return DecisionPreview(annie=annie, mikasa=mikasa, eren=None, erwin=None, correlation_id=correlation_id, final_message=f"HOLD: {exc}")
        adjusted_confidence = (eren.confidence * mikasa.confidence_multiplier).quantize(Decimal("0.0001"))
        adjusted_risk = min(
            profile.risk_per_trade_pct,
            (eren.expected_risk_pct * mikasa.risk_multiplier).quantize(Decimal("0.0001")),
        )
        eren = eren.model_copy(update={
            "confidence": adjusted_confidence,
            "expected_risk_pct": adjusted_risk,
            "reasons": (*eren.reasons, f"Mikasa advisory score {mikasa.quality_score}/10; risk multiplier {mikasa.risk_multiplier}"),
        })
        erwin = self._erwin.evaluate(eren, account, profile, market.spread)
        return DecisionPreview(
            annie=annie,
            mikasa=mikasa,
            eren=eren,
            erwin=erwin,
            correlation_id=correlation_id,
            final_message=f"{erwin.status.value}: {erwin.reasons[0]}",
        )
