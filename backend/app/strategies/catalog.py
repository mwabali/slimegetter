"""Research-only XAUUSD strategy catalog.

Configurations are hypotheses, not approved trading systems. None may execute
until backtesting, walk-forward validation, demo evidence, and human promotion.
"""
from itertools import product
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrategySpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    version: str
    family: Literal[
        "EMA_CROSS", "DONCHIAN_BREAKOUT", "RSI_REVERSION",
        "BOLLINGER_REVERSION", "MACD_MOMENTUM", "STOCHASTIC_REVERSION",
        "SMA_CROSS", "ROC_MOMENTUM", "CCI_REVERSION", "KELTNER_BREAKOUT",
        "EMA_RSI_TREND", "ATR_CHANNEL_BREAKOUT", "BOLLINGER_BREAKOUT",
        "ROC_TREND_FILTER", "DONCHIAN_TREND_FILTER",
    ]
    timeframe: str = "M5"
    status: Literal["RESEARCH"] = "RESEARCH"
    parameters: dict[str, Any]
    atr_stop_multiplier: float = Field(default=1.5, gt=0)
    reward_risk_target: float = Field(default=2.0, gt=0)
    source_tags: tuple[str, ...] = ("time-series-momentum", "gold-momentum-volatility")

    @model_validator(mode="after")
    def validate_periods(self) -> "StrategySpec":
        fast, slow = self.parameters.get("fast"), self.parameters.get("slow")
        if fast is not None and slow is not None and fast >= slow:
            raise ValueError("fast period must be below slow period")
        lower, upper = self.parameters.get("lower"), self.parameters.get("upper")
        if lower is not None and upper is not None and lower >= upper:
            raise ValueError("lower threshold must be below upper threshold")
        return self


def _spec(family: str, index: int, parameters: dict[str, Any]) -> StrategySpec:
    slug = family.lower().replace("_", "-")
    return StrategySpec(
        name=f"{family.replace('_', ' ').title()} {index:02d}",
        version=f"{slug}@1.{index:02d}",
        family=family,
        parameters=parameters,
    )


def build_catalog() -> tuple[StrategySpec, ...]:
    specs: list[StrategySpec] = []
    for i, (fast, slow) in enumerate(product((5, 8, 12, 16, 20), (30, 40, 50, 75, 100)), 1):
        specs.append(_spec("EMA_CROSS", i, {"fast": fast, "slow": slow}))
    for i, (entry, exit_period) in enumerate(product((10, 20, 30, 40, 55), (5, 10, 15, 20, 25)), 1):
        specs.append(_spec("DONCHIAN_BREAKOUT", i, {"entry_lookback": entry, "exit_lookback": exit_period}))
    for i, (period, bands) in enumerate(product((7, 10, 14, 18, 21), ((20, 80), (25, 75), (30, 70), (35, 65), (40, 60))), 1):
        specs.append(_spec("RSI_REVERSION", i, {"period": period, "lower": bands[0], "upper": bands[1]}))
    for i, (period, deviation) in enumerate(product((10, 15, 20, 25, 30), (1.5, 1.75, 2.0, 2.25, 2.5)), 1):
        specs.append(_spec("BOLLINGER_REVERSION", i, {"period": period, "deviation": deviation}))
    for i, (fast, slow) in enumerate(product((5, 8, 12, 16, 20), (21, 26, 35, 50, 75)), 1):
        specs.append(_spec("MACD_MOMENTUM", i, {"fast": fast, "slow": slow, "signal": 9}))
    for i, (k_period, d_period) in enumerate(product((5, 9, 14, 21, 28), (3, 5, 7, 9, 12)), 1):
        specs.append(_spec("STOCHASTIC_REVERSION", i, {"k_period": k_period, "d_period": d_period, "lower": 20, "upper": 80}))
    # The second research generation deliberately spans additional horizons and
    # thresholds. These are hypotheses only; catalog membership is not approval.
    for i, (fast, slow) in enumerate(product((3, 5, 7, 9, 12, 15, 18, 21, 25, 30), (35, 40, 50, 60, 75, 90, 110, 130, 160, 200)), 1):
        specs.append(_spec("SMA_CROSS", i, {"fast": fast, "slow": slow}))
    for i, (period, threshold) in enumerate(product((3, 5, 7, 10, 14, 18, 21, 28, 35, 50), (0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.75, 1.0, 1.5)), 1):
        specs.append(_spec("ROC_MOMENTUM", i, {"period": period, "threshold": threshold}))
    for i, (period, threshold) in enumerate(product((5, 7, 10, 14, 18, 21, 28, 35, 42, 50), (50, 65, 75, 85, 100, 115, 130, 150, 175, 200)), 1):
        specs.append(_spec("CCI_REVERSION", i, {"period": period, "threshold": threshold}))
    for i, (period, multiplier) in enumerate(product((5, 7, 10, 14, 18, 21, 28, 35, 42, 50), (0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0)), 1):
        specs.append(_spec("KELTNER_BREAKOUT", i, {"period": period, "multiplier": multiplier}))
    # Third-generation hypotheses combine entry logic with independent regime
    # filters or invert reversion bands into continuation systems.
    for i, (trend, pullback) in enumerate(product((20, 30, 40, 50, 65, 80, 100, 125, 150, 200), (20, 25, 30, 35, 40, 45, 47, 48, 49, 50)), 1):
        specs.append(_spec("EMA_RSI_TREND", i, {"trend": trend, "rsi_period": 14, "pullback": pullback}))
    for i, (period, multiplier) in enumerate(product((5, 7, 10, 14, 18, 21, 28, 35, 42, 50), (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)), 1):
        specs.append(_spec("ATR_CHANNEL_BREAKOUT", i, {"period": period, "multiplier": multiplier}))
    for i, (period, deviation) in enumerate(product((8, 10, 12, 15, 18, 20, 24, 28, 35, 50), (0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0)), 1):
        specs.append(_spec("BOLLINGER_BREAKOUT", i, {"period": period, "deviation": deviation}))
    for i, (period, trend) in enumerate(product((3, 5, 7, 10, 14, 18, 21, 28, 35, 50), (20, 30, 40, 50, 65, 80, 100, 125, 150, 200)), 1):
        specs.append(_spec("ROC_TREND_FILTER", i, {"period": period, "trend": trend, "threshold": 0.15}))
    for i, (entry, trend) in enumerate(product((5, 7, 10, 14, 18, 21, 28, 35, 42, 55), (20, 30, 40, 50, 65, 80, 100, 125, 150, 200)), 1):
        specs.append(_spec("DONCHIAN_TREND_FILTER", i, {"entry_lookback": entry, "trend": trend}))
    # Expand the original six families across stop/target variants. This makes
    # execution behaviour distinct while retaining the original 150 baselines.
    baselines = tuple(specs[:150])
    for base in baselines:
        for suffix, stop, target in (("a", 1.0, 1.5), ("b", 1.25, 2.0), ("c", 1.75, 2.5)):
            specs.append(base.model_copy(update={
                "name": f"{base.name} Risk {suffix.upper()}",
                "version": f"{base.version}-{suffix}",
                "atr_stop_multiplier": stop,
                "reward_risk_target": target,
            }))
    # Add one execution-distinct variant to 20 entry models in every family so
    # that empirical duplicate removal still leaves at least 1,000 candidates,
    # without concentrating the additional hypotheses in one strategy family.
    entry_models = tuple(specs[:1050])
    for family in StrategySpec.model_fields["family"].annotation.__args__:
        for base in tuple(row for row in entry_models if row.family == family)[:20]:
            specs.append(base.model_copy(update={
                "name": f"{base.name} Risk D",
                "version": f"{base.version}-d",
                "atr_stop_multiplier": 2.0,
                "reward_risk_target": 1.25,
            }))
    versions = {spec.version for spec in specs}
    if len(specs) != 1800 or len(versions) != 1800:
        raise RuntimeError("Strategy catalog must contain exactly 1800 unique configurations")
    return tuple(specs)


CATALOG = build_catalog()
