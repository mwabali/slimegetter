from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.application.workflows.decision_preview import DecisionPreview, DecisionPreviewWorkflow
from app.agents.mikasa.models import SimilarMarketPerformance
from app.domain.market.models import MarketSession, MarketSnapshot
from app.domain.trading.models import AccountSnapshot, RiskProfile
from app.infrastructure.mt5.gateway import MetaTrader5Gateway, Mt5Bar
from app.infrastructure.market_data.providers import EconomicCalendarProvider


def _ema(values: list[Decimal], period: int) -> Decimal:
    value = values[0]; multiplier = Decimal("2") / Decimal(period + 1)
    for close in values[1:]: value = (close - value) * multiplier + value
    return value


def _rsi(closes: list[Decimal], period: int = 14) -> Decimal:
    moves = [closes[i] - closes[i - 1] for i in range(1, len(closes))][-period:]
    gains = sum((move for move in moves if move > 0), Decimal("0")); losses = abs(sum((move for move in moves if move < 0), Decimal("0")))
    return Decimal("100") if losses == 0 else Decimal("100") - (Decimal("100") / (Decimal("1") + gains / losses))


class ShadowModeRunner:
    """Read-only live pipeline. This class never imports or calls an execution service."""
    def run_once(
        self,
        gateway: MetaTrader5Gateway,
        profile: RiskProfile,
        calendar: EconomicCalendarProvider,
        max_tick_age_seconds: int = 15,
        max_bar_age_seconds: int = 600,
        server_utc_offset_hours: int = 0,
        minimum_market_quality: Decimal = Decimal("7.00"),
        observation_override: bool = False,
        similar_market_performance: SimilarMarketPerformance | None = None,
    ) -> DecisionPreview:
        gateway.connect()
        try:
            account = gateway.get_account_snapshot(); tick = gateway.get_tick("XAUUSD"); bars = gateway.get_recent_bars("XAUUSD")
            now = datetime.now(UTC)
            offset = timedelta(hours=server_utc_offset_hours)
            tick_time = datetime.fromtimestamp(tick.time_msc / 1000, UTC) - offset
            tick_age = (now - tick_time).total_seconds()
            if tick_age < -5 or tick_age > max_tick_age_seconds:
                raise RuntimeError("XAUUSD tick is stale; fail closed")
            bar_age = (now - (bars[-1].time - offset)).total_seconds()
            if bar_age < -300 or bar_age > max_bar_age_seconds:
                raise RuntimeError("XAUUSD M5 bars are stale; fail closed")
            events = calendar.upcoming_gold_events()
            closes = [bar.close for bar in bars]; atr = sum((bar.high - bar.low for bar in bars[-14:]), Decimal("0")) / Decimal("14")
            fast, slow, rsi = _ema(closes[-30:], 12), _ema(closes[-40:], 26), _rsi(closes)
            strength = min(Decimal("10"), abs(fast - slow) / atr * Decimal("2")) if atr else Decimal("0")
            market = MarketSnapshot(bid=tick.bid, ask=tick.ask, atr=atr, ema_fast=fast, ema_slow=slow, rsi=rsi, trend_strength=strength, volatility_score=Decimal("7"), liquidity_score=Decimal("8"), momentum_score=min(Decimal("10"), abs(rsi - Decimal("50")) / Decimal("5")), session=MarketSession.LONDON)
            return DecisionPreviewWorkflow().run(
                market,
                events,
                0,
                account,
                profile,
                minimum_market_quality,
                observation_override,
                similar_market_performance,
            )
        finally:
            gateway.shutdown()
