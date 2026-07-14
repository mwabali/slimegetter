from decimal import Decimal
from uuid import UUID

from app.domain.market.models import MarketSnapshot
from app.domain.trading.models import Side, TradeProposal


class ErenService:
    """Produces a structured strategy proposal only; it cannot execute or approve a trade."""

    def generate(
        self, market: MarketSnapshot, expected_risk_pct: Decimal, correlation_id: UUID
    ) -> TradeProposal:
        bullish = market.ema_fast > market.ema_slow and market.rsi >= Decimal("55")
        bearish = market.ema_fast < market.ema_slow and market.rsi <= Decimal("45")
        if not bullish and not bearish:
            raise ValueError("Strategy has no directional setup")
        side = Side.BUY if bullish else Side.SELL
        entry = market.ask if side is Side.BUY else market.bid
        stop_distance = market.atr * Decimal("1.5")
        target_distance = stop_distance * Decimal("2")
        stop_loss = entry - stop_distance if side is Side.BUY else entry + stop_distance
        take_profit = entry + target_distance if side is Side.BUY else entry - target_distance
        direction = "bullish" if side is Side.BUY else "bearish"
        return TradeProposal(
            correlation_id=correlation_id,
            side=side,
            volume=Decimal("0.01"),
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=Decimal("0.65"),
            reasons=(f"Fast EMA / slow EMA alignment is {direction}", "RSI confirms momentum"),
            indicators_used=("EMA", "RSI", "ATR"),
            expected_risk_pct=expected_risk_pct,
            session=market.session.value,
        )
