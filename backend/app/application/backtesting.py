"""Small deterministic EMA/RSI/ATR backtest used for research only."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.infrastructure.mt5.gateway import Mt5Bar


class BacktestTrade(BaseModel):
    model_config = ConfigDict(frozen=True)
    opened_at: datetime
    closed_at: datetime
    side: str
    entry: Decimal
    exit: Decimal
    pnl: Decimal
    reward_risk: Decimal


class BacktestResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    strategy_version: str
    bars: int
    trades: tuple[BacktestTrade, ...]
    net_pnl: Decimal
    win_rate: Decimal | None
    profit_factor: Decimal | None
    maximum_drawdown: Decimal


def _ema(values: list[Decimal], period: int) -> Decimal:
    value = values[0]
    multiplier = Decimal("2") / Decimal(period + 1)
    for current in values[1:]:
        value = (current - value) * multiplier + value
    return value


def _rsi(values: list[Decimal], period: int = 14) -> Decimal:
    moves = [values[index] - values[index - 1] for index in range(1, len(values))][-period:]
    gains = sum((move for move in moves if move > 0), Decimal("0"))
    losses = abs(sum((move for move in moves if move < 0), Decimal("0")))
    return Decimal("100") if not losses else Decimal("100") - Decimal("100") / (Decimal("1") + gains / losses)


def run_ema_rsi_backtest(bars: tuple[Mt5Bar, ...], strategy_version: str = "ema-rsi@1.0") -> BacktestResult:
    if len(bars) < 40:
        raise ValueError("At least 40 bars are required for a deterministic backtest")
    trades: list[BacktestTrade] = []
    for index in range(40, len(bars)):
        closes = [bar.close for bar in bars[: index + 1]]
        fast, slow, rsi = _ema(closes[-30:], 12), _ema(closes[-40:], 26), _rsi(closes)
        if not ((fast > slow and rsi >= 55) or (fast < slow and rsi <= 45)):
            continue
        current = bars[index]
        side = "BUY" if fast > slow else "SELL"
        entry = current.close
        atr = sum((bar.high - bar.low for bar in bars[index - 14 : index]), Decimal("0")) / Decimal("14")
        risk = atr * Decimal("1.5")
        target = risk * Decimal("2")
        stop = entry - risk if side == "BUY" else entry + risk
        take = entry + target if side == "BUY" else entry - target
        exit_price = bars[index + 1].close if index + 1 < len(bars) else entry
        if side == "BUY":
            exit_price = min(max(exit_price, stop), take)
        else:
            exit_price = max(min(exit_price, stop), take)
        pnl = exit_price - entry if side == "BUY" else entry - exit_price
        trades.append(BacktestTrade(opened_at=current.time, closed_at=bars[min(index + 1, len(bars) - 1)].time, side=side, entry=entry, exit=exit_price, pnl=pnl, reward_risk=abs(pnl / risk) if risk else Decimal("0")))
    running = peak = drawdown = Decimal("0")
    for trade in trades:
        running += trade.pnl
        peak = max(peak, running)
        drawdown = max(drawdown, peak - running)
    wins = sum(1 for trade in trades if trade.pnl > 0)
    gains = sum((trade.pnl for trade in trades if trade.pnl > 0), Decimal("0"))
    losses = abs(sum((trade.pnl for trade in trades if trade.pnl < 0), Decimal("0")))
    return BacktestResult(strategy_version=strategy_version, bars=len(bars), trades=tuple(trades), net_pnl=sum((trade.pnl for trade in trades), Decimal("0")), win_rate=Decimal(wins) / len(trades) if trades else None, profit_factor=gains / losses if losses else None, maximum_drawdown=drawdown)
