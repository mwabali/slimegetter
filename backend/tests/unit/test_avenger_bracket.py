from decimal import Decimal
from uuid import uuid4

from app.application.avenger import AvengerBracketBuilder
from app.config.settings import get_settings
from app.domain.market.models import MarketSession, MarketSnapshot


def market(*, spread: str = "0.20", momentum: str = "8.0") -> MarketSnapshot:
    bid = Decimal("4010.00")
    return MarketSnapshot(
        bid=bid,
        ask=bid + Decimal(spread),
        atr=Decimal("1.00"),
        ema_fast=Decimal("4011.00"),
        ema_slow=Decimal("4010.50"),
        rsi=Decimal("62"),
        trend_strength=Decimal("5"),
        volatility_score=Decimal("7"),
        liquidity_score=Decimal("8"),
        momentum_score=Decimal(momentum),
        session=MarketSession.LONDON,
    )


def test_flash_bracket_uses_tradingbot_style_spread_adjusted_trigger(monkeypatch) -> None:
    monkeypatch.setenv("XAU_AVENGER_PROFILE_MODE", "FLASH")
    get_settings.cache_clear()
    try:
        plan = AvengerBracketBuilder().build(
            market(spread="0.50"), get_settings(), Decimal("0.25"), uuid4()
        )
        assert plan.profile_name == "FLASH"
        assert plan.effective_trigger == Decimal("1.500")
        assert plan.buy.order_type == "BUY_STOP"
        assert plan.sell.order_type == "SELL_STOP"
        assert plan.buy.proposal.entry_price == Decimal("4012.00")
        assert plan.buy.proposal.stop_loss == Decimal("4010.50")
        assert plan.buy.proposal.take_profit == Decimal("4018.00")
        assert plan.sell.proposal.entry_price == Decimal("4008.50")
        assert plan.sell.proposal.stop_loss == Decimal("4010.00")
        assert plan.sell.proposal.take_profit == Decimal("4002.50")
    finally:
        get_settings.cache_clear()


def test_hybrid_selects_thor_when_flash_impulse_conditions_are_not_clean(monkeypatch) -> None:
    monkeypatch.setenv("XAU_AVENGER_PROFILE_MODE", "HYBRID")
    get_settings.cache_clear()
    try:
        plan = AvengerBracketBuilder().build(
            market(spread="0.20", momentum="3.0"),
            get_settings(),
            Decimal("0.25"),
            uuid4(),
        )
        assert plan.profile_name == "THOR"
        assert plan.effective_trigger == Decimal("2.0")
        assert plan.trail_distance == Decimal("0.8")
    finally:
        get_settings.cache_clear()
