"""Manage open MT5 demo positions and journal exits for learning."""
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from app.application.mt5_sync import Mt5ReadOnlySynchronizer
from app.config.settings import get_settings
from app.domain.journal.repository import TradeJournalRepository
from app.infrastructure.mt5.gateway import MetaTrader5Gateway, Mt5Position
from app.infrastructure.persistence.database import SessionLocal


STATE_OPEN = "OPEN"
STATE_MONITORING = "MONITORING"
STATE_BREAKEVEN_ARMED = "BREAKEVEN_ARMED"
STATE_BREAKEVEN_CONFIRMED = "BREAKEVEN_CONFIRMED"
STATE_PROFIT_LOCK_ARMED = "PROFIT_LOCK_ARMED"
STATE_PROFIT_LOCK_CONFIRMED = "PROFIT_LOCK_CONFIRMED"
STATE_TRAILING_ACTIVE = "TRAILING_ACTIVE"
STATE_EXIT_TRIGGERED = "EXIT_TRIGGERED"
STATE_CLOSE_REQUEST_SENT = "CLOSE_REQUEST_SENT"
STATE_MARKET_CLOSED_COOLDOWN = "MARKET_CLOSED_COOLDOWN"
STATE_CLOSE_CONFIRMED = "CLOSE_CONFIRMED"
STATE_CLOSE_FAILED = "CLOSE_FAILED"
CLOSE_CONFIRM_POLLS = 3
CLOSE_CONFIRM_SLEEP_SECONDS = 0.5
CLOSE_RETRY_ATTEMPTS = 3
XAU_CONTRACT_SIZE = Decimal("100")
PIXIS_AGENT = "PIXIS"
PROTECTION_ORDER = {
    STATE_OPEN: 0,
    STATE_MONITORING: 1,
    STATE_BREAKEVEN_ARMED: 2,
    STATE_BREAKEVEN_CONFIRMED: 3,
    STATE_PROFIT_LOCK_ARMED: 4,
    STATE_PROFIT_LOCK_CONFIRMED: 5,
    STATE_TRAILING_ACTIVE: 6,
    STATE_EXIT_TRIGGERED: 7,
    STATE_CLOSE_REQUEST_SENT: 8,
    STATE_MARKET_CLOSED_COOLDOWN: 8,
    STATE_CLOSE_CONFIRMED: 9,
    STATE_CLOSE_FAILED: 9,
}


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
        "status": STATE_OPEN,
        "first_seen_at": now,
        "peak_profit": current_profit,
        "trough_profit": current_profit,
        "last_profit": current_profit,
        "last_seen_at": now,
        "observations": 0,
        "close_attempt_count": 0,
    })
    record.setdefault("status", STATE_MONITORING)
    record.setdefault("close_attempt_count", 0)
    record.setdefault("active_exit_policy", get_settings().demo_position_exit_policy)
    record.setdefault("profit_basis", get_settings().demo_position_profit_basis)
    record.setdefault("entry_price", str(position.price_open))
    record.setdefault("initial_stop_loss", str(position.stop_loss) if position.stop_loss is not None else None)
    record.setdefault("initial_take_profit", str(position.take_profit) if position.take_profit is not None else None)
    record.setdefault("initial_volume", str(position.volume))
    if record.get("initial_risk_usd") is None and position.stop_loss is not None:
        risk_price = abs(position.price_open - position.stop_loss)
        record["initial_risk_price"] = str(risk_price)
        record["initial_risk_usd"] = str((risk_price * position.volume * XAU_CONTRACT_SIZE).quantize(Decimal("0.01")))
    record["peak_profit"] = max(float(record.get("peak_profit", current_profit)), current_profit)
    record["trough_profit"] = min(float(record.get("trough_profit", current_profit)), current_profit)
    record["last_profit"] = current_profit
    initial_risk = Decimal(str(record.get("initial_risk_usd") or "0"))
    if initial_risk > 0:
        record["current_r"] = str((position.profit / initial_risk).quantize(Decimal("0.0001")))
        record["peak_r"] = str((Decimal(str(record["peak_profit"])) / initial_risk).quantize(Decimal("0.0001")))
    record["last_seen_at"] = now
    record["observations"] = int(record.get("observations", 0)) + 1
    if record["status"] == STATE_OPEN:
        record["status"] = STATE_MONITORING
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


def _advance_state(memory: dict[str, object], new_state: str) -> None:
    current = str(memory.get("status", STATE_MONITORING))
    if PROTECTION_ORDER.get(new_state, 0) >= PROTECTION_ORDER.get(current, 0):
        memory["status"] = new_state


def _profit_price(position: Mt5Position, profit_usd: Decimal) -> Decimal:
    price_delta = profit_usd / (position.volume * XAU_CONTRACT_SIZE)
    return position.price_open + price_delta if position.side == "BUY" else position.price_open - price_delta


def _protective_stop_improves(position: Mt5Position, proposed_stop: Decimal, current_stop: Decimal | None) -> bool:
    if current_stop is None:
        return True
    settings = get_settings()
    improvement = Decimal(str(settings.demo_position_min_sl_improvement_price))
    if position.side == "BUY":
        return proposed_stop >= current_stop + improvement
    return proposed_stop <= current_stop - improvement


def _can_modify_sl(memory: dict[str, object]) -> bool:
    last = memory.get("last_sl_modified_at")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last))
    except ValueError:
        return True
    return (datetime.now(UTC) - last_dt).total_seconds() >= get_settings().demo_position_min_sl_modify_seconds


def _modify_stop(
    gateway: MetaTrader5Gateway,
    repository: TradeJournalRepository,
    position: Mt5Position,
    memory: dict[str, object],
    new_stop: Decimal,
    event_type: str,
) -> Mt5Position:
    if not _can_modify_sl(memory) or not _protective_stop_improves(position, new_stop, position.stop_loss):
        return position
    memory["last_sl_modify_requested_at"] = datetime.now(UTC).isoformat()
    confirmed = gateway.modify_position_protection(position, new_stop, position.take_profit, f"xau-manager:{event_type}")
    memory["broker_stop_loss"] = str(confirmed.stop_loss)
    memory["broker_take_profit"] = str(confirmed.take_profit)
    memory["last_sl_modified_at"] = datetime.now(UTC).isoformat()
    _record_manager_event(repository, event_type, _manager_payload(confirmed, memory, event_type, new_stop=str(new_stop)))
    return confirmed


def _allowed_giveback(memory: dict[str, object]) -> Decimal:
    settings = get_settings()
    peak = Decimal(str(memory.get("peak_profit", 0)))
    return max(
        Decimal(str(settings.demo_position_trailing_giveback_usd)),
        peak * Decimal(str(settings.demo_position_trailing_giveback_pct)),
        Decimal(str(settings.demo_position_spread_cost_buffer_usd)),
    )


def _hybrid_close_reason(
    gateway: MetaTrader5Gateway,
    repository: TradeJournalRepository,
    position: Mt5Position,
    memory: dict[str, object],
) -> str | None:
    settings = get_settings()
    if position.stop_loss is None or position.take_profit is None:
        return "MISSING_BROKER_PROTECTION"
    age_minutes = _position_age_minutes(position)
    initial_risk = Decimal(str(memory.get("initial_risk_usd") or "0"))
    current_r = position.profit / initial_risk if initial_risk > 0 else Decimal("0")
    breakeven_activation = Decimal(str(settings.demo_position_breakeven_activation_usd))
    if position.profit >= breakeven_activation or (initial_risk > 0 and current_r >= Decimal(str(settings.demo_position_breakeven_activation_r))):
        _advance_state(memory, STATE_BREAKEVEN_ARMED)
        breakeven_stop = _profit_price(position, Decimal(str(settings.demo_position_breakeven_buffer_usd)))
        try:
            position = _modify_stop(gateway, repository, position, memory, breakeven_stop, "BREAKEVEN_CONFIRMED")
            _advance_state(memory, STATE_BREAKEVEN_CONFIRMED)
            memory["breakeven_level"] = str(breakeven_stop)
        except Exception as exc:
            memory["latest_mt5_error"] = f"{type(exc).__name__}: {exc}"
            _record_manager_event(repository, "BREAKEVEN_MODIFY_FAILED", _manager_payload(position, memory, "BREAKEVEN_MODIFY_FAILED", error=memory["latest_mt5_error"]))
    lock_activation = Decimal(str(settings.demo_position_profit_lock_activation_usd))
    lock_profit = Decimal(str(settings.demo_position_profit_lock_usd))
    if position.profit >= lock_activation or (initial_risk > 0 and current_r >= Decimal(str(settings.demo_position_profit_lock_activation_r))):
        _advance_state(memory, STATE_PROFIT_LOCK_ARMED)
        lock_stop = _profit_price(position, lock_profit if initial_risk <= 0 else max(lock_profit, initial_risk * Decimal(str(settings.demo_position_profit_lock_r))))
        memory["locked_profit_floor"] = str(lock_profit)
        try:
            position = _modify_stop(gateway, repository, position, memory, lock_stop, "PROFIT_LOCK_CONFIRMED")
            _advance_state(memory, STATE_PROFIT_LOCK_CONFIRMED)
        except Exception as exc:
            memory["latest_mt5_error"] = f"{type(exc).__name__}: {exc}"
            _record_manager_event(repository, "PROFIT_LOCK_MODIFY_FAILED", _manager_payload(position, memory, "PROFIT_LOCK_MODIFY_FAILED", error=memory["latest_mt5_error"]))
    peak_profit = Decimal(str(memory.get("peak_profit", position.profit)))
    trailing_ready = (
        int(memory.get("observations", 0)) >= settings.demo_position_min_trailing_observations
        and (
            peak_profit >= Decimal(str(settings.demo_position_trailing_activation_usd))
            or (initial_risk > 0 and Decimal(str(memory.get("peak_r", "0"))) >= Decimal(str(settings.demo_position_trailing_activation_r)))
        )
    )
    if trailing_ready:
        _advance_state(memory, STATE_TRAILING_ACTIVE)
        allowed = _allowed_giveback(memory)
        floor = peak_profit - allowed
        memory["allowed_giveback"] = str(allowed)
        memory["trailing_floor"] = str(floor)
        if position.profit <= floor:
            return "HYBRID_TRAILING_FLOOR_BREACHED"
    if settings.demo_position_stop_loss_usd and position.profit <= -Decimal(str(settings.demo_position_stop_loss_usd)):
        return "LEARNING_STOP_LIMIT"
    if age_minutes >= settings.demo_position_max_minutes:
        return "LEARNING_MAX_AGE"
    if settings.demo_position_close_on_opposite_signal and age_minutes >= 1 and _opposite_signal(gateway, position):
        return "LEARNING_OPPOSITE_SIGNAL"
    return None


def _close_reason(gateway: MetaTrader5Gateway, position: Mt5Position, memory: dict[str, object], repository: TradeJournalRepository | None = None) -> str | None:
    settings = get_settings()
    age_minutes = _position_age_minutes(position)
    peak_profit = Decimal(str(memory.get("peak_profit", position.profit)))
    giveback = peak_profit - position.profit
    dynamic_giveback = max(
        Decimal(str(settings.demo_position_trailing_giveback_usd)),
        peak_profit * Decimal(str(settings.demo_position_trailing_giveback_pct)),
    )
    if position.stop_loss is None or position.take_profit is None:
        return "MISSING_BROKER_PROTECTION"
    if settings.demo_position_exit_policy == "HYBRID_PROFIT_PROTECTION" and repository is not None:
        return _hybrid_close_reason(gateway, repository, position, memory)
    if settings.demo_position_exit_policy == "VALIDATION_FIXED_TARGET" and settings.demo_position_validation_target_usd and position.profit >= Decimal(str(settings.demo_position_validation_target_usd)):
        return "VALIDATION_FIXED_TARGET"
    if settings.demo_position_exit_policy == "FIXED_TAKE_PROFIT" and settings.demo_position_profit_target_usd and position.profit >= Decimal(str(settings.demo_position_profit_target_usd)):
        return "LEARNING_PROFIT_TARGET"
    if (
        settings.demo_position_trailing_activation_usd
        and peak_profit >= Decimal(str(settings.demo_position_trailing_activation_usd))
        and giveback >= dynamic_giveback
    ):
        return "LEARNING_TRAILING_PROFIT_PROTECTION"
    if settings.demo_position_stop_loss_usd and position.profit <= -Decimal(str(settings.demo_position_stop_loss_usd)):
        return "LEARNING_STOP_LIMIT"
    if age_minutes >= settings.demo_position_max_minutes:
        return "LEARNING_MAX_AGE"
    if settings.demo_position_close_on_opposite_signal and age_minutes >= 1 and _opposite_signal(gateway, position):
        return "LEARNING_OPPOSITE_SIGNAL"
    return None


def _find_position(gateway: MetaTrader5Gateway, symbol: str, ticket: str) -> Mt5Position | None:
    return next((position for position in gateway.get_positions(symbol) if position.ticket == ticket), None)


def _manager_payload(position: Mt5Position, memory: dict[str, object], reason: str, **extra: object) -> dict[str, object]:
    return {
        "source_ticket": position.ticket,
        "symbol": position.symbol,
        "side": position.side,
        "volume": str(position.volume),
        "open_profit_at_close_request": str(position.profit),
        "peak_profit_seen": str(memory.get("peak_profit")),
        "trough_profit_seen": str(memory.get("trough_profit")),
        "age_minutes": round(_position_age_minutes(position), 2),
        "reason": reason,
        "status": memory.get("status"),
        "close_attempt_count": int(memory.get("close_attempt_count", 0)),
        **extra,
    }


def _record_manager_event(repository: TradeJournalRepository, event_type: str, payload: dict[str, object]) -> None:
    with SessionLocal() as session:
        repository.record_collective_events(session, uuid4(), ((1, PIXIS_AGENT, event_type, json.dumps(payload)),))


def _record_close_failure_alert(repository: TradeJournalRepository, position_ticket: str, message: str) -> None:
    with SessionLocal() as session:
        repository.create_execution_incident(
            session,
            incident_type="CLOSE_FAILED",
            severity="CRITICAL",
            position_ticket=position_ticket,
            message=message,
        )
        repository.record_heartbeat(session, "demo-position-manager", "ERROR", message)


def _is_managed_avenger_order(order: object) -> bool:
    comment = str(getattr(order, "comment", "") or "")
    magic = getattr(order, "magic", None)
    return comment.startswith("xau-avenger:") or magic == 260713


def _cancel_opposite_avenger_pending_orders(
    gateway: MetaTrader5Gateway,
    repository: TradeJournalRepository,
    positions: tuple[Mt5Position, ...],
) -> int:
    if not positions:
        return 0
    get_orders = getattr(gateway, "get_orders", None)
    cancel_order = getattr(gateway, "cancel_order", None)
    if not callable(get_orders) or not callable(cancel_order):
        return 0
    cancelled = 0
    for order in tuple(get_orders("XAUUSD")):
        if not _is_managed_avenger_order(order):
            continue
        try:
            cancel_ticket = cancel_order(order, "xau-avenger:oco-cancel")
            cancelled += 1
            _record_manager_event(
                repository,
                "AVENGER_OPPOSITE_PENDING_CANCELLED",
                {
                    "order_ticket": getattr(order, "ticket", None),
                    "cancel_ticket": cancel_ticket,
                    "reason": "A bracket leg filled; Pixis removed remaining managed pending exposure",
                },
            )
        except Exception as exc:
            _record_manager_event(
                repository,
                "AVENGER_PENDING_CANCEL_FAILED",
                {
                    "order_ticket": getattr(order, "ticket", None),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
    return cancelled


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _is_market_closed_error(message: str) -> bool:
    lowered = message.lower()
    return "market closed" in lowered or "retcode=10018" in lowered


def _set_market_closed_cooldown(memory: dict[str, object], error: str) -> None:
    next_retry = datetime.now(UTC) + timedelta(minutes=get_settings().demo_position_market_closed_cooldown_minutes)
    memory["status"] = STATE_MARKET_CLOSED_COOLDOWN
    memory["latest_mt5_error"] = error
    memory["cooldown_reason"] = "MARKET_CLOSED"
    memory["next_retry_after"] = next_retry.isoformat()


def _cooldown_active(memory: dict[str, object]) -> bool:
    if memory.get("status") != STATE_MARKET_CLOSED_COOLDOWN:
        return False
    next_retry = _parse_time(memory.get("next_retry_after"))
    return bool(next_retry and datetime.now(UTC) < next_retry)


def _latched_close_reason(gateway: MetaTrader5Gateway, position: Mt5Position, memory: dict[str, object], repository: TradeJournalRepository) -> str | None:
    if memory.get("status") in {STATE_EXIT_TRIGGERED, STATE_CLOSE_REQUEST_SENT, STATE_CLOSE_FAILED, STATE_MARKET_CLOSED_COOLDOWN}:
        if _cooldown_active(memory):
            return None
        if memory.get("status") == STATE_MARKET_CLOSED_COOLDOWN:
            memory["status"] = STATE_CLOSE_FAILED
        if memory.get("status") == STATE_CLOSE_FAILED:
            last_dt = _parse_time(memory.get("last_close_requested_at"))
            if last_dt and (datetime.now(UTC) - last_dt).total_seconds() < get_settings().demo_position_failed_close_retry_seconds:
                return None
        return str(memory.get("pending_exit_reason") or "LATCHED_EXIT")
    reason = _close_reason(gateway, position, memory, repository)
    if reason is None:
        return None
    now = datetime.now(UTC).isoformat()
    memory["status"] = STATE_EXIT_TRIGGERED
    memory["pending_exit_reason"] = reason
    memory["triggered_at"] = now
    memory["last_exit_check_at"] = now
    return reason


def _close_and_confirm(
    gateway: MetaTrader5Gateway,
    repository: TradeJournalRepository,
    position: Mt5Position,
    memory: dict[str, object],
    reason: str,
) -> bool:
    memory["status"] = STATE_CLOSE_REQUEST_SENT
    memory["last_close_requested_at"] = datetime.now(UTC).isoformat()
    latest_error = None
    for _ in range(CLOSE_RETRY_ATTEMPTS):
        current = _find_position(gateway, position.symbol, position.ticket)
        if current is None:
            memory["status"] = STATE_CLOSE_CONFIRMED
            memory["confirmed_at"] = datetime.now(UTC).isoformat()
            _record_manager_event(repository, "DEMO_POSITION_CLOSE_CONFIRMED", _manager_payload(position, memory, reason))
            return True
        try:
            close_ticket = gateway.close_position(current, f"xau-manager:{reason}")
            memory["latest_close_ticket"] = close_ticket
            memory["latest_mt5_error"] = None
            memory["close_attempt_count"] = int(memory.get("close_attempt_count", 0)) + 1
            _record_manager_event(
                repository,
                "DEMO_POSITION_CLOSE_REQUEST_SENT",
                _manager_payload(current, memory, reason, close_ticket=close_ticket),
            )
        except Exception as exc:
            latest_error = f"{type(exc).__name__}: {exc}"
            memory["latest_mt5_error"] = latest_error
            memory["close_attempt_count"] = int(memory.get("close_attempt_count", 0)) + 1
            _record_manager_event(repository, "DEMO_POSITION_CLOSE_FAILED", _manager_payload(current, memory, reason, error=latest_error))
            if _is_market_closed_error(latest_error):
                _set_market_closed_cooldown(memory, latest_error)
                _record_manager_event(
                    repository,
                    "MARKET_CLOSED_COOLDOWN",
                    _manager_payload(current, memory, reason, error=latest_error, next_retry_after=memory.get("next_retry_after")),
                )
                _record_close_failure_alert(
                    repository,
                    position.ticket,
                    f"Market is closed for {position.symbol} ticket {position.ticket}; close retries paused until {memory.get('next_retry_after')}.",
                )
                return False
        for _ in range(CLOSE_CONFIRM_POLLS):
            if _find_position(gateway, position.symbol, position.ticket) is None:
                memory["status"] = STATE_CLOSE_CONFIRMED
                memory["confirmed_at"] = datetime.now(UTC).isoformat()
                _record_manager_event(repository, "DEMO_POSITION_CLOSE_CONFIRMED", _manager_payload(position, memory, reason))
                return True
            time.sleep(CLOSE_CONFIRM_SLEEP_SECONDS)
    memory["status"] = STATE_CLOSE_FAILED
    memory["latest_mt5_error"] = latest_error or "Close request sent but MT5 still reports the position open"
    _record_close_failure_alert(
        repository,
        position.ticket,
        f"Demo position close failed repeatedly for {position.symbol} ticket {position.ticket}; new entries must remain blocked.",
    )
    return False


def run_once() -> dict[str, int]:
    settings = get_settings()
    if not settings.demo_position_manager_enabled:
        return {"closed": 0, "open": 0}
    if not settings.execution_enabled or settings.kill_switch_active or settings.trading_mode != "demo":
        raise RuntimeError("Pixis requires demo execution with kill switch off")

    repository = TradeJournalRepository()
    synchronizer = Mt5ReadOnlySynchronizer()
    gateway = MetaTrader5Gateway.from_installed_package(allow_orders=True, kill_switch=lambda: get_settings().kill_switch_active)
    gateway.connect()
    closed = 0
    state = _load_state()
    try:
        positions = gateway.get_positions("XAUUSD")
        cancelled_pending = _cancel_opposite_avenger_pending_orders(gateway, repository, positions)
        seen_tickets = {position.ticket for position in positions}
        now = datetime.now(UTC).isoformat()
        for ticket, record in tuple(state.items()):
            if ticket not in seen_tickets and record.get("status") != STATE_CLOSE_CONFIRMED:
                record["status"] = STATE_CLOSE_CONFIRMED
                record["confirmed_at"] = now
                record["latest_mt5_error"] = None
                record.setdefault("pending_exit_reason", "BROKER_OR_MANUAL_CLOSE_RECONCILED")
                _record_manager_event(repository, "DEMO_POSITION_RECONCILED_CLOSED", {"source_ticket": ticket, **record})
        with SessionLocal() as session:
            repository.record_heartbeat(session, "demo-position-manager", "RUNNING", f"Pixis managing {len(positions)} open XAUUSD position(s); cancelled_pending={cancelled_pending}")
            synchronizer.sync_positions(session, positions)
        for position in positions:
            memory = _update_position_memory(position, state)
            reason = _latched_close_reason(gateway, position, memory, repository)
            if reason is None:
                continue
            _record_manager_event(repository, "DEMO_POSITION_EXIT_TRIGGERED", _manager_payload(position, memory, reason))
            if _close_and_confirm(gateway, repository, position, memory, reason):
                closed += 1
        since = datetime.now(UTC) - timedelta(days=7)
        until = datetime.now(UTC) + timedelta(hours=settings.mt5_server_utc_offset_hours)
        fills = gateway.get_recent_fills(since, until)
        with SessionLocal() as session:
            synchronizer.sync_fills(session, fills)
            active = [
                f"{position.ticket}:{state.get(position.ticket, {}).get('status', STATE_MONITORING)}"
                f"/p={position.profit}/peak={state.get(position.ticket, {}).get('peak_profit')}"
                f"/policy={state.get(position.ticket, {}).get('active_exit_policy', settings.demo_position_exit_policy)}"
                f"/target={settings.demo_position_validation_target_usd if settings.demo_position_exit_policy == 'VALIDATION_FIXED_TARGET' else settings.demo_position_profit_target_usd}"
                f"/reason={state.get(position.ticket, {}).get('pending_exit_reason', '-')}"
                f"/floor={state.get(position.ticket, {}).get('trailing_floor', '-')}"
                f"/nextRetry={state.get(position.ticket, {}).get('next_retry_after', '-')}"
                f"/attempts={state.get(position.ticket, {}).get('close_attempt_count', 0)}"
                for position in positions
            ]
            repository.record_heartbeat(
                session,
                "demo-position-manager",
                "HEALTHY",
                f"Open={len(positions)} closed={closed}; fills synced={len(fills)}; " + "; ".join(active),
            )
    finally:
        _save_state(state)
        gateway.shutdown()
    return {"closed": closed, "open": len(positions)}


if __name__ == "__main__":
    print(json.dumps(run_once()))
