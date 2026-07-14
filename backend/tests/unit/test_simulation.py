from decimal import Decimal
from datetime import UTC, datetime

from app.application.simulation import bar_is_after_entry, evaluate_bar


def test_simulation_uses_conservative_stop_first_ordering() -> None:
    result = evaluate_bar("BUY", Decimal("100"), Decimal("99"), Decimal("102"), Decimal("103"), Decimal("98"))
    assert result is not None
    assert result.reason == "STOP_LOSS"
    assert result.pnl_per_unit == Decimal("-1")


def test_simulation_handles_short_take_profit() -> None:
    result = evaluate_bar("SELL", Decimal("100"), Decimal("101"), Decimal("98"), Decimal("100.5"), Decimal("97.5"))
    assert result is not None
    assert result.reason == "TAKE_PROFIT"
    assert result.pnl_per_unit == Decimal("2")


def test_simulation_never_uses_the_entry_candle() -> None:
    opened = datetime(2026, 1, 1, 10, 3, tzinfo=UTC)
    assert not bar_is_after_entry(opened, datetime(2026, 1, 1, 10, 0, tzinfo=UTC))
    assert bar_is_after_entry(opened, datetime(2026, 1, 1, 10, 5, tzinfo=UTC))
