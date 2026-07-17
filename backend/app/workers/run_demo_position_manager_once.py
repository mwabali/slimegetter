"""Manage open MT5 demo positions and journal exits for learning."""
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.application.mt5_sync import Mt5ReadOnlySynchronizer
from app.config.settings import get_settings
from app.domain.journal.repository import TradeJournalRepository
from app.infrastructure.mt5.gateway import MetaTrader5Gateway, Mt5Position
from app.infrastructure.persistence.database import SessionLocal


def _position_age_minutes(position: Mt5Position) -> float:
    if position.opened_at is None:
        return 0
    opened = position.opened_at if position.opened_at.tzinfo else position.opened_at.replace(tzinfo=UTC)
    offset = timedelta(hours=get_settings().mt5_server_utc_offset_hours)
    opened = opened - offset
    return max(0, (datetime.now(UTC) - opened).total_seconds() / 60)


def _load_state() -> dict[str, dict[str, object]]:
    path = Path(get_settings().demo_position_state_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_state(state: dict[str, dict[str, object]]) -> None:
    path = Path(get_settings().demo_position_state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _update_position_memory(position: Mt5Position, state: dict[str, dict[str, object]]) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    current_profit = float(position.profit)
    record = state.setdefault(position.ticket, {
        "ticket": position.ticket,
        "symbol": position.symbol,
        "side": position.side,
        "first_seen_at": now,
        "peak_profit": current_profit,
        "trough_profit": current_profit,
        "last_profit": current_profit,
        "last_seen_at": now,
        "observations": 0,
    })
    record["peak_profit"] = max(float(record.get("peak_profit", current_profit)), current_profit)
    record["trough_profit"] = min(float(record.get("trough_profit", current_profit)), current_profit)
    record["last_profit"] = current_profit
    record["last_seen_at"] = now
    record["observations"] = int(record.get("observations", 0)) + 1
    return record


def _opposite_signal(gateway: MetaTrader5Gateway, position: Mt5Position) -> bool:
    bars = gateway.get_recent_bars(position.symbol, 50)
    closes = [bar.close for bar in bars]
    fast = sum(closes[-12:], Decimal("0")) / Decimal("12")
    slow = sum(closes[-26:], Decimal("0")) / Decimal("26")
    recent = closes[-1] - closes[-4]
    if position.side == "BUY":
        return fast < slow and recent < 0
    return fast > slow and recent > 0


def _close_reason(gateway: MetaTrader5Gateway, position: Mt5Position, memory: dict[str, object]) -> str | None:
    settings = get_settings()
    age_minutes = _position_age_minutes(position)
    peak_profit = Decimal(str(memory.get("peak_profit", position.profit)))
    giveback = peak_profit - position.profit
    dynamic_giveback = max(
        Decimal(str(settings.demo_position_trailing_giveback_usd)),
        peak_profit * Decimal(str(settings.demo_position_trailing_giveback_pct)),
    )
    if (
        settings.demo_position_trailing_activation_usd
        and peak_profit >= Decimal(str(settings.demo_position_trailing_activation_usd))
        and giveback >= dynamic_giveback
    ):
        return "LEARNING_TRAILING_PROFIT_PROTECTION"
    if settings.demo_position_profit_target_usd and position.profit >= Decimal(str(settings.demo_position_profit_target_usd)):
        return "LEARNING_PROFIT_TARGET"
    if settings.demo_position_stop_loss_usd and position.profit <= -Decimal(str(settings.demo_position_stop_loss_usd)):
        return "LEARNING_STOP_LIMIT"
    if age_minutes >= settings.demo_position_max_minutes:
        return "LEARNING_MAX_AGE"
    if settings.demo_position_close_on_opposite_signal and age_minutes >= 1 and _opposite_signal(gateway, position):
        return "LEARNING_OPPOSITE_SIGNAL"
    return None


def run_once() -> dict[str, int]:
    settings = get_settings()
    if not settings.demo_position_manager_enabled:
        return {"closed": 0, "open": 0}
    if not settings.execution_enabled or settings.kill_switch_active or settings.trading_mode != "demo":
        raise RuntimeError("Demo position manager requires demo execution with kill switch off")

    repository = TradeJournalRepository()
    synchronizer = Mt5ReadOnlySynchronizer()
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=True, kill_switch=lambda: get_settings().kill_switch_active)
    gateway.connect()
    closed = 0
    state = _load_state()
    try:
        positions = gateway.get_positions("XAUUSD")
        seen_tickets = {position.ticket for position in positions}
        for ticket in tuple(state):
            if ticket not in seen_tickets:
                state.pop(ticket, None)
        with SessionLocal() as session:
            repository.record_heartbeat(session, "demo-position-manager", "RUNNING", f"Managing {len(positions)} open XAUUSD position(s)")
            synchronizer.sync_positions(session, positions)
        for position in positions:
            memory = _update_position_memory(position, state)
            reason = _close_reason(gateway, position, memory)
            if reason is None:
                continue
            ticket = gateway.close_position(position, f"xau-manager:{reason}")
            closed += 1
            correlation_id = uuid4()
            with SessionLocal() as session:
                repository.record_collective_events(session, correlation_id, (
                    (1, "POSITION_MANAGER", "DEMO_POSITION_CLOSED", json.dumps({
                        "source_ticket": position.ticket,
                        "close_ticket": ticket,
                        "symbol": position.symbol,
                        "side": position.side,
                        "volume": str(position.volume),
                        "open_profit_at_close_request": str(position.profit),
                        "peak_profit_seen": str(memory.get("peak_profit")),
                        "trough_profit_seen": str(memory.get("trough_profit")),
                        "age_minutes": round(_position_age_minutes(position), 2),
                        "reason": reason,
                    })),
                ))
            state.pop(position.ticket, None)
        since = datetime.now(UTC) - timedelta(days=7)
        until = datetime.now(UTC) + timedelta(hours=settings.mt5_server_utc_offset_hours)
        fills = gateway.get_recent_fills(since, until)
        with SessionLocal() as session:
            synchronizer.sync_fills(session, fills)
            repository.record_heartbeat(session, "demo-position-manager", "HEALTHY", f"Open={len(positions)} closed={closed}; fills synced={len(fills)}")
    finally:
        _save_state(state)
        gateway.shutdown()
    return {"closed": closed, "open": len(positions)}


if __name__ == "__main__":
    print(json.dumps(run_once()))
