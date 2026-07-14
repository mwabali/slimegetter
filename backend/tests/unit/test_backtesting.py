from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.application.backtesting import run_ema_rsi_backtest
from app.infrastructure.mt5.gateway import Mt5Bar


def test_backtest_is_reproducible() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars = tuple(
        Mt5Bar(start + timedelta(minutes=5 * index), Decimal(str(2300 + index)), Decimal(str(2301 + index)), Decimal(str(2299 + index)), Decimal(str(2300 + index)))
        for index in range(60)
    )
    first = run_ema_rsi_backtest(bars)
    second = run_ema_rsi_backtest(bars)
    assert first == second
    assert first.bars == 60
