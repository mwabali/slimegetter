from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.config.settings import Settings
from app.domain.market.models import MarketSnapshot
from app.domain.trading.models import Side, TradeProposal


@dataclass(frozen=True)
class AvengerProfile:
    name: str
    trigger: Decimal
    stop: Decimal
    take_profit: Decimal
    trail: Decimal


@dataclass(frozen=True)
class PendingOrderPlan:
    proposal: TradeProposal
    order_type: str
    comment: str


@dataclass(frozen=True)
class AvengerBracketPlan:
    profile_name: str
    symbol: str
    effective_trigger: Decimal
    spread: Decimal
    trail_distance: Decimal
    expires_at: datetime
    buy: PendingOrderPlan
    sell: PendingOrderPlan


class AvengerBracketBuilder:
    """Build TradingBot-style XAUUSD pending straddles without broker side effects."""

    def build(
        self,
        market: MarketSnapshot,
        settings: Settings,
        expected_risk_pct: Decimal,
        correlation_id: UUID,
    ) -> AvengerBracketPlan:
        profile = self._select_profile(market, settings)
        spread_buffer = market.spread * Decimal(str(settings.avenger_trigger_spread_multiplier))
        minimum_trigger = Decimal(str(settings.avenger_min_effective_trigger_price))
        effective_trigger = max(profile.trigger, spread_buffer, minimum_trigger)
        volume = Decimal(str(settings.avenger_volume))
        expires_at = datetime.now(UTC) + timedelta(
            minutes=settings.avenger_pending_expiration_minutes
        )

        buy_entry = market.ask + effective_trigger
        sell_entry = market.bid - effective_trigger
        buy = TradeProposal(
            correlation_id=correlation_id,
            side=Side.BUY,
            volume=volume,
            entry_price=buy_entry,
            stop_loss=buy_entry - profile.stop,
            take_profit=buy_entry + profile.take_profit,
            confidence=Decimal("0.70") if profile.name == "THOR" else Decimal("0.66"),
            reasons=(
                f"Avenger {profile.name} pending bracket: buy-stop above ask by effective trigger",
                (
                    f"Trigger=max(raw {profile.trigger}, spread buffer {spread_buffer}, "
                    f"minimum {minimum_trigger})"
                ),
            ),
            indicators_used=("AVENGER_STRADDLE", profile.name, "SPREAD_ADJUSTED_TRIGGER"),
            expected_risk_pct=expected_risk_pct,
            session=market.session.value,
        )
        sell = TradeProposal(
            correlation_id=correlation_id,
            side=Side.SELL,
            volume=volume,
            entry_price=sell_entry,
            stop_loss=sell_entry + profile.stop,
            take_profit=sell_entry - profile.take_profit,
            confidence=Decimal("0.70") if profile.name == "THOR" else Decimal("0.66"),
            reasons=(
                f"Avenger {profile.name} pending bracket: sell-stop below bid by effective trigger",
                (
                    f"Trigger=max(raw {profile.trigger}, spread buffer {spread_buffer}, "
                    f"minimum {minimum_trigger})"
                ),
            ),
            indicators_used=("AVENGER_STRADDLE", profile.name, "SPREAD_ADJUSTED_TRIGGER"),
            expected_risk_pct=expected_risk_pct,
            session=market.session.value,
        )
        return AvengerBracketPlan(
            profile_name=profile.name,
            symbol=market.symbol,
            effective_trigger=effective_trigger,
            spread=market.spread,
            trail_distance=profile.trail,
            expires_at=expires_at,
            buy=PendingOrderPlan(buy, "BUY_STOP", f"xau-avenger:{profile.name}:BUY"),
            sell=PendingOrderPlan(sell, "SELL_STOP", f"xau-avenger:{profile.name}:SELL"),
        )

    @staticmethod
    def _select_profile(market: MarketSnapshot, settings: Settings) -> AvengerProfile:
        thor = AvengerProfile(
            "THOR",
            Decimal(str(settings.avenger_thor_trigger_price)),
            Decimal(str(settings.avenger_thor_stop_price)),
            Decimal(str(settings.avenger_thor_take_profit_price)),
            Decimal(str(settings.avenger_thor_trail_price)),
        )
        flash = AvengerProfile(
            "FLASH",
            Decimal(str(settings.avenger_flash_trigger_price)),
            Decimal(str(settings.avenger_flash_stop_price)),
            Decimal(str(settings.avenger_flash_take_profit_price)),
            Decimal(str(settings.avenger_flash_trail_price)),
        )
        if settings.avenger_profile_mode == "THOR":
            return thor
        if settings.avenger_profile_mode == "FLASH":
            return flash
        clean_impulse = (
            market.momentum_score >= Decimal(str(settings.avenger_flash_min_momentum_score))
            and market.spread <= Decimal(str(settings.avenger_flash_max_spread_price))
            and market.liquidity_score >= Decimal("5")
        )
        return flash if clean_impulse else thor
