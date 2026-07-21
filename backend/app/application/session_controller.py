"""Historical EAT session windows for the restored Avenger strategy."""
from dataclasses import dataclass
from datetime import UTC, datetime, time
from enum import StrEnum
from zoneinfo import ZoneInfo


EAT = ZoneInfo("Africa/Nairobi")


class SessionState(StrEnum):
    COOLED_DOWN = "COOLED_DOWN"
    PRE_WINDOW_CHECK = "PRE_WINDOW_CHECK"
    AUTHORIZED_WINDOW = "AUTHORIZED_WINDOW"
    TRADING = "TRADING"
    WINDOW_ENDING = "WINDOW_ENDING"
    COOLING_DOWN = "COOLING_DOWN"
    SESSION_ANALYSIS = "SESSION_ANALYSIS"


@dataclass(frozen=True)
class TradingWindow:
    key: str
    start: time
    end: time

    def contains(self, local_time: time) -> bool:
        return self.start <= local_time < self.end


@dataclass(frozen=True)
class SessionDecision:
    state: SessionState
    authorized: bool
    window: TradingWindow | None
    checked_at: datetime
    reason: str


# Recovered from the Avenger CEO-FD configuration. These are EAT windows.
HISTORICAL_WINDOWS = (
    TradingWindow("EAT_03_05", time(3, 0), time(5, 0)),
    TradingWindow("EAT_16_22", time(16, 0), time(22, 0)),
)


def current_eat(now_utc: datetime | None = None) -> datetime:
    value = now_utc or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(EAT)


def active_window(now_utc: datetime | None = None) -> TradingWindow | None:
    local = current_eat(now_utc)
    return next((window for window in HISTORICAL_WINDOWS if window.contains(local.time())), None)


def evaluate_session(
    now_utc: datetime | None = None,
    *,
    mt5_connected: bool = True,
    demo_account: bool = True,
    market_open: bool = True,
    symbol_valid: bool = True,
    no_open_position: bool = True,
    no_orphan_pending_orders: bool = True,
    broker_trade_allowed: bool = True,
    workers_healthy: bool = True,
    spread_within_limit: bool = True,
) -> SessionDecision:
    checked_at = current_eat(now_utc)
    window = active_window(now_utc)
    if window is None:
        return SessionDecision(
            SessionState.COOLED_DOWN,
            False,
            None,
            checked_at,
            "Outside recovered Avenger EAT trading windows",
        )
    checks = {
        "MT5 connected": mt5_connected,
        "demo account": demo_account,
        "market open": market_open,
        "symbol valid": symbol_valid,
        "no open position": no_open_position,
        "no orphan pending orders": no_orphan_pending_orders,
        "broker trading permission": broker_trade_allowed,
        "required workers healthy": workers_healthy,
        "spread within historical limit": spread_within_limit,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        return SessionDecision(
            SessionState.PRE_WINDOW_CHECK,
            False,
            window,
            checked_at,
            "Pre-window check failed: " + ", ".join(failed),
        )
    return SessionDecision(
        SessionState.TRADING,
        True,
        window,
        checked_at,
        f"Authorized in recovered {window.key} window",
    )
