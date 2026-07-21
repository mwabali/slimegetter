import pytest

from app.config.settings import get_settings
from app.workers.run_demo_once import run_once


def test_demo_worker_is_blocked_by_default(monkeypatch) -> None:
    monkeypatch.delenv("XAU_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("XAU_DEMO_TRADING_CONFIRMED", raising=False)
    monkeypatch.delenv("XAU_KILL_SWITCH_ACTIVE", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="requires"):
            run_once()
    finally:
        get_settings.cache_clear()


def test_kill_switch_defaults_active() -> None:
    get_settings.cache_clear()
    try:
        assert get_settings().kill_switch_active is True
    finally:
        get_settings.cache_clear()


def test_entry_poll_interval_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv("XAU_DEMO_ENTRY_POLL_SECONDS", "7")
    get_settings.cache_clear()
    try:
        assert get_settings().demo_entry_poll_seconds == 7
    finally:
        get_settings.cache_clear()


def test_demo_exploration_floor_is_calibrated_and_opposite_exit_is_opt_in() -> None:
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.demo_exploration_min_market_quality == 4.0
        assert settings.demo_position_close_on_opposite_signal is False
    finally:
        get_settings.cache_clear()
