from datetime import UTC, datetime
from decimal import Decimal

from app.config.settings import get_settings
from app.infrastructure.mt5.gateway import Mt5Position
from app.workers import run_demo_position_manager_once as manager


def position(
    *,
    ticket: str = "123",
    side: str = "BUY",
    profit: str = "0",
    stop_loss: Decimal | None = Decimal("4000"),
    take_profit: Decimal | None = Decimal("4020"),
) -> Mt5Position:
    return Mt5Position(
        ticket=ticket,
        symbol="XAUUSD",
        side=side,
        volume=Decimal("0.01"),
        price_open=Decimal("4010"),
        stop_loss=stop_loss,
        take_profit=take_profit,
        profit=Decimal(profit),
        opened_at=datetime.now(UTC),
    )


def configure_manager(monkeypatch, *, target: str = "2.00", activation: str = "0.50", policy: str = "VALIDATION_FIXED_TARGET") -> None:
    monkeypatch.setenv("XAU_DEMO_POSITION_EXIT_POLICY", policy)
    monkeypatch.setenv("XAU_DEMO_POSITION_VALIDATION_TARGET_USD", target)
    monkeypatch.setenv("XAU_DEMO_POSITION_PROFIT_TARGET_USD", target)
    monkeypatch.setenv("XAU_DEMO_POSITION_TRAILING_ACTIVATION_USD", activation)
    monkeypatch.setenv("XAU_DEMO_POSITION_TRAILING_GIVEBACK_USD", "0.30")
    monkeypatch.setenv("XAU_DEMO_POSITION_TRAILING_GIVEBACK_PCT", "0.35")
    monkeypatch.setenv("XAU_DEMO_POSITION_MAX_MINUTES", "999")
    monkeypatch.setenv("XAU_DEMO_POSITION_CLOSE_ON_OPPOSITE_SIGNAL", "false")
    get_settings.cache_clear()


class StaticGateway:
    def __init__(self, positions):
        self.positions = list(positions)
        self.close_calls = 0

    def get_positions(self, symbol=None):
        return tuple(self.positions)

    def close_position(self, open_position, comment):
        self.close_calls += 1
        return f"close-{self.close_calls}"

    def modify_position_protection(self, open_position, stop_loss, take_profit, comment):
        updated = open_position.__class__(
            ticket=open_position.ticket,
            symbol=open_position.symbol,
            side=open_position.side,
            volume=open_position.volume,
            price_open=open_position.price_open,
            stop_loss=stop_loss if stop_loss is not None else open_position.stop_loss,
            take_profit=take_profit if take_profit is not None else open_position.take_profit,
            profit=open_position.profit,
            opened_at=open_position.opened_at,
        )
        self.positions = [updated if p.ticket == updated.ticket else p for p in self.positions]
        return updated


def test_profit_target_beats_trailing_when_both_are_true(monkeypatch) -> None:
    configure_manager(monkeypatch)
    try:
        reason = manager._close_reason(StaticGateway(()), position(profit="2.01"), {"peak_profit": 5.0})
        assert reason == "VALIDATION_FIXED_TARGET"
    finally:
        get_settings.cache_clear()


def test_profit_target_boundary_uses_greater_than_or_equal(monkeypatch) -> None:
    configure_manager(monkeypatch, activation="5.00")
    try:
        assert manager._close_reason(StaticGateway(()), position(profit="1.99"), {"peak_profit": 1.99}) is None
        assert manager._close_reason(StaticGateway(()), position(profit="2.01"), {"peak_profit": 2.01}) == "VALIDATION_FIXED_TARGET"
    finally:
        get_settings.cache_clear()


def test_latched_exit_survives_profit_falling_back(monkeypatch) -> None:
    configure_manager(monkeypatch)
    memory = {
        "status": manager.STATE_EXIT_TRIGGERED,
        "pending_exit_reason": "LEARNING_PROFIT_TARGET",
        "peak_profit": 2.12,
    }
    try:
        assert manager._latched_close_reason(StaticGateway(()), position(profit="0.25"), memory, object()) == "LEARNING_PROFIT_TARGET"
    finally:
        get_settings.cache_clear()


def test_missing_broker_protection_closes_before_monitoring(monkeypatch) -> None:
    configure_manager(monkeypatch)
    try:
        reason = manager._close_reason(StaticGateway(()), position(profit="0.10", stop_loss=None), {"peak_profit": 0.1})
        assert reason == "MISSING_BROKER_PROTECTION"
    finally:
        get_settings.cache_clear()


def test_close_is_confirmed_only_after_position_disappears(monkeypatch) -> None:
    open_position = position(profit="2.10")
    gateway = StaticGateway((open_position,))

    def close_and_remove(current, comment):
        gateway.close_calls += 1
        gateway.positions = []
        return "close-ticket"

    monkeypatch.setattr(gateway, "close_position", close_and_remove)
    monkeypatch.setattr(manager, "_record_manager_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager.time, "sleep", lambda seconds: None)

    memory = {"status": manager.STATE_EXIT_TRIGGERED, "pending_exit_reason": "LEARNING_PROFIT_TARGET", "peak_profit": 2.1}
    assert manager._close_and_confirm(gateway, object(), open_position, memory, "LEARNING_PROFIT_TARGET") is True
    assert memory["status"] == manager.STATE_CLOSE_CONFIRMED


def test_close_failure_remains_latched_when_position_stays_open(monkeypatch) -> None:
    open_position = position(profit="2.10")
    gateway = StaticGateway((open_position,))
    monkeypatch.setattr(manager, "_record_manager_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "_record_close_failure_alert", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(manager, "CLOSE_RETRY_ATTEMPTS", 2)
    monkeypatch.setattr(manager, "CLOSE_CONFIRM_POLLS", 1)

    memory = {"status": manager.STATE_EXIT_TRIGGERED, "pending_exit_reason": "LEARNING_PROFIT_TARGET", "peak_profit": 2.1}
    assert manager._close_and_confirm(gateway, object(), open_position, memory, "LEARNING_PROFIT_TARGET") is False
    assert memory["status"] == manager.STATE_CLOSE_FAILED
    assert memory["close_attempt_count"] == 2


def test_hybrid_does_not_close_at_two_dollars(monkeypatch) -> None:
    configure_manager(monkeypatch, policy="HYBRID_PROFIT_PROTECTION")
    monkeypatch.setattr(manager, "_record_manager_event", lambda *args, **kwargs: None)
    open_position = position(profit="2.01", stop_loss=Decimal("4009"), take_profit=Decimal("4020"))
    memory = {
        "status": manager.STATE_MONITORING,
        "peak_profit": 2.01,
        "observations": 3,
        "initial_risk_usd": "1.00",
    }
    try:
        reason = manager._close_reason(StaticGateway((open_position,)), open_position, memory, object())
        assert reason is None
        assert memory["status"] in {manager.STATE_PROFIT_LOCK_CONFIRMED, manager.STATE_TRAILING_ACTIVE}
        assert memory.get("locked_profit_floor") == "1.0"
    finally:
        get_settings.cache_clear()


def test_hybrid_closes_when_trailing_floor_is_breached(monkeypatch) -> None:
    configure_manager(monkeypatch, policy="HYBRID_PROFIT_PROTECTION")
    monkeypatch.setattr(manager, "_record_manager_event", lambda *args, **kwargs: None)
    open_position = position(profit="3.00", stop_loss=Decimal("4010.01"), take_profit=Decimal("4020"))
    memory = {
        "status": manager.STATE_TRAILING_ACTIVE,
        "peak_profit": 5.00,
        "observations": 10,
        "initial_risk_usd": "1.00",
    }
    try:
        assert manager._close_reason(StaticGateway((open_position,)), open_position, memory, object()) == "HYBRID_TRAILING_FLOOR_BREACHED"
        assert Decimal(str(memory["trailing_floor"])) == Decimal("3.25")
    finally:
        get_settings.cache_clear()


def test_failed_close_retry_is_throttled(monkeypatch) -> None:
    configure_manager(monkeypatch)
    memory = {
        "status": manager.STATE_CLOSE_FAILED,
        "pending_exit_reason": "VALIDATION_FIXED_TARGET",
        "last_close_requested_at": datetime.now(UTC).isoformat(),
    }
    try:
        assert manager._latched_close_reason(StaticGateway(()), position(profit="2.00"), memory, object()) is None
    finally:
        get_settings.cache_clear()


def test_market_closed_failure_sets_cooldown(monkeypatch) -> None:
    configure_manager(monkeypatch)
    monkeypatch.setenv("XAU_DEMO_POSITION_MARKET_CLOSED_COOLDOWN_MINUTES", "120")
    get_settings.cache_clear()
    open_position = position(profit="-1.00")
    gateway = StaticGateway((open_position,))

    def market_closed(current, comment):
        gateway.close_calls += 1
        raise RuntimeError("MT5 close rejected: retcode=10018 comment=Market closed")

    monkeypatch.setattr(gateway, "close_position", market_closed)
    monkeypatch.setattr(manager, "_record_manager_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager, "_record_close_failure_alert", lambda *args, **kwargs: None)
    monkeypatch.setattr(manager.time, "sleep", lambda seconds: None)

    memory = {"status": manager.STATE_EXIT_TRIGGERED, "pending_exit_reason": "LEARNING_MAX_AGE", "peak_profit": -0.1}
    try:
        assert manager._close_and_confirm(gateway, object(), open_position, memory, "LEARNING_MAX_AGE") is False
        assert memory["status"] == manager.STATE_MARKET_CLOSED_COOLDOWN
        assert memory["cooldown_reason"] == "MARKET_CLOSED"
        assert memory.get("next_retry_after")
        assert gateway.close_calls == 1
    finally:
        get_settings.cache_clear()


def test_market_closed_cooldown_blocks_latched_retry(monkeypatch) -> None:
    configure_manager(monkeypatch)
    memory = {
        "status": manager.STATE_MARKET_CLOSED_COOLDOWN,
        "pending_exit_reason": "LEARNING_MAX_AGE",
        "next_retry_after": "2999-01-01T00:00:00+00:00",
    }
    try:
        assert manager._latched_close_reason(StaticGateway(()), position(profit="-1.00"), memory, object()) is None
    finally:
        get_settings.cache_clear()
