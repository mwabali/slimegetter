import pytest

from app.domain.trading.models import TradeLifecycleStatus, validate_transition


def test_trade_lifecycle_allows_audited_path() -> None:
    path = (
        TradeLifecycleStatus.CREATED, TradeLifecycleStatus.ANALYZED,
        TradeLifecycleStatus.PROPOSED, TradeLifecycleStatus.APPROVED,
        TradeLifecycleStatus.SUBMITTED, TradeLifecycleStatus.FILLED,
        TradeLifecycleStatus.CLOSED,
    )
    for current, target in zip(path, path[1:]):
        validate_transition(current, target)


def test_trade_lifecycle_refuses_bypassing_erwin() -> None:
    with pytest.raises(ValueError, match="Invalid trade state transition"):
        validate_transition(TradeLifecycleStatus.PROPOSED, TradeLifecycleStatus.SUBMITTED)
