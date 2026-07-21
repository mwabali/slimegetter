from datetime import UTC, datetime

from app.application.session_controller import SessionState, evaluate_session


def test_recovered_eat_windows_authorize_trading() -> None:
    decision = evaluate_session(datetime(2026, 7, 21, 1, 30, tzinfo=UTC))
    assert decision.state is SessionState.TRADING
    assert decision.authorized is True
    assert decision.window is not None
    assert decision.window.key == "EAT_03_05"


def test_outside_recovered_windows_cools_down() -> None:
    decision = evaluate_session(datetime(2026, 7, 21, 10, 0, tzinfo=UTC))
    assert decision.state is SessionState.COOLED_DOWN
    assert decision.authorized is False


def test_pre_window_checks_block_entry() -> None:
    decision = evaluate_session(
        datetime(2026, 7, 21, 1, 30, tzinfo=UTC),
        broker_trade_allowed=False,
    )
    assert decision.state is SessionState.PRE_WINDOW_CHECK
    assert "broker trading permission" in decision.reason
