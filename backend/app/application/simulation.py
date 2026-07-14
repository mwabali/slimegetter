"""Deterministic paper-position barrier evaluation with no broker access."""
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal


@dataclass(frozen=True)
class SimulatedExit:
    price: Decimal
    reason: str
    pnl_per_unit: Decimal


def bar_is_after_entry(opened_at: datetime, bar_time: datetime) -> bool:
    opened = opened_at if opened_at.tzinfo else opened_at.replace(tzinfo=UTC)
    bar = bar_time if bar_time.tzinfo else bar_time.replace(tzinfo=UTC)
    return bar > opened


def evaluate_bar(side: str, entry: Decimal, stop: Decimal, target: Decimal, high: Decimal, low: Decimal) -> SimulatedExit | None:
    """Resolve stop before target when both occur inside one OHLC bar."""
    direction = Decimal("1") if side == "BUY" else Decimal("-1")
    stop_hit = low <= stop if side == "BUY" else high >= stop
    target_hit = high >= target if side == "BUY" else low <= target
    if stop_hit:
        return SimulatedExit(stop, "STOP_LOSS", (stop - entry) * direction)
    if target_hit:
        return SimulatedExit(target, "TAKE_PROFIT", (target - entry) * direction)
    return None
