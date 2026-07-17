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


def configure_manager(monkeypatch, *, target: str = "2.00", activation: str = "0.50") -> None:
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


def test_profit_target_beats_trailing_when_both_are_true(monkeypatch) -> None:
    configure_manager(monkeypatch)
    try:
        reason = manager._close_reason(StaticGateway(()), position(profit="2.01"), {"peak_profit": 5.0})
        assert reason == "LEARNING_PROFIT_TARGET"
    finally:
        get_settings.cache_clear()


def test_profit_target_boundary_uses_greater_than_or_equal(monkeypatch) -> None:
    configure_manager(monkeypatch, activation="5.00")
    try:
        assert manager._close_reason(StaticGateway(()), position(profit="1.99"), {"peak_profit": 1.99}) is None
        assert manager._close_reason(StaticGateway(()), position(profit="2.01"), {"peak_profit": 2.01}) == "LEARNING_PROFIT_TARGET"
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
        assert manager._latched_close_reason(StaticGateway(()), position(profit="0.25"), memory) == "LEARNING_PROFIT_TARGET"
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
