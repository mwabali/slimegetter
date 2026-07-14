"""Immutable research policy fixed before the 1,000-candidate experiment."""
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ValidationPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str = "xauusd-research-policy@2.0.0"
    development_fraction: Decimal = Decimal("0.60")
    walk_forward_fraction: Decimal = Decimal("0.20")
    untouched_holdout_fraction: Decimal = Decimal("0.20")
    minimum_walk_forward_trades: int = 30
    minimum_profit_factor: Decimal = Decimal("1.10")
    minimum_holdout_profit_factor: Decimal = Decimal("1.05")
    minimum_positive_walk_forward_windows: int = 2
    maximum_signal_correlation: Decimal = Decimal("0.90")
    false_discovery_rate: Decimal = Decimal("0.05")
    shadow_minimum_observations: int = 50
    shadow_minimum_actionable_outcomes: int = 10
    shadow_minimum_profit_factor: Decimal = Decimal("1.10")
    human_promotion_required: bool = True
    automatic_live_promotion: bool = False


LOCKED_POLICY = ValidationPolicy()
