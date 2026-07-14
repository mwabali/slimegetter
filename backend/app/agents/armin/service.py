from collections import defaultdict
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TradeOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)
    strategy_version: str
    session: str
    pnl: Decimal
    reward_risk: Decimal = Field(ge=0)


class PerformanceReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    trade_count: int
    profit_factor: Decimal | None
    maximum_drawdown: Decimal
    best_session: str | None
    learning_notes: tuple[str, ...]


class ArminService:
    """Read-only performance analysis; it cannot tune a live strategy."""
    def analyze(self, trades: tuple[TradeOutcome, ...]) -> PerformanceReport:
        if not trades:
            return PerformanceReport(trade_count=0, profit_factor=None, maximum_drawdown=Decimal("0"), best_session=None, learning_notes=("No closed trades",))
        profit = sum((x.pnl for x in trades if x.pnl > 0), Decimal("0")); loss = abs(sum((x.pnl for x in trades if x.pnl < 0), Decimal("0")))
        sessions: dict[str, Decimal] = defaultdict(Decimal); running = peak = dd = Decimal("0")
        for trade in trades:
            sessions[trade.session] += trade.pnl; running += trade.pnl; peak = max(peak, running); dd = max(dd, peak - running)
        return PerformanceReport(trade_count=len(trades), profit_factor=profit / loss if loss else None, maximum_drawdown=dd, best_session=max(sessions, key=sessions.get), learning_notes=("Backtest and human approval are required before promotion",))
