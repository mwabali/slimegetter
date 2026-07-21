"""Historical EAT session windows for the restored Avenger strategy."""
from dataclasses import dataclass
from datetime import UTC, datetime, time
from enum import StrEnum
import os
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


def configured_windows() -> tuple[TradingWindow, ...]:
    """Return an optional demo-only schedule without changing production defaults."""
    raw = os.getenv("XAU_DEMO_SESSION_WINDOWS", "").strip()
    if not raw:
        return HISTORICAL_WINDOWS
    windows: list[TradingWindow] = []
    try:
        for item in raw.split(","):
            start_text, end_text = (part.strip() for part in item.split("-", 1))
            start = time.fromisoformat(start_text)
            end = time.fromisoformat(end_text)
            if start >= end:
                raise ValueError("window must not cross midnight or be empty")
            key = f"DEMO_{start.strftime('%H%M')}_{end.strftime('%H%M')}"
            windows.append(TradingWindow(key, start, end))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Invalid XAU_DEMO_SESSION_WINDOWS; expected HH:MM-HH:MM entries") from exc
    if not windows:
        raise RuntimeError("XAU_DEMO_SESSION_WINDOWS must contain at least one window")
    return tuple(windows)


def current_eat(now_utc: datetime | None = None) -> datetime:
    value = now_utc or datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(EAT)


def active_window(now_utc: datetime | None = None) -> TradingWindow | None:
    local = current_eat(now_utc)
    return next((window for window in configured_windows() if window.contains(local.time())), None)


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
    demo_override = os.getenv("XAU_DEMO_SESSION_OVERRIDE", "false").lower() == "true"
    if demo_override:
        window = TradingWindow("DEMO_OVERRIDE", time(0, 0), time(23, 59, 59))
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
            (
                "Authorized by explicit demo-only session override"
                if demo_override
                else f"Authorized in recovered {window.key} window"
            ),
        )
