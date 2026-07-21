from decimal import Decimal
from uuid import uuid4

import pytest

from app.agents.erwin.service import CommanderErwinService
from app.infrastructure.mt5.gateway import ExecutionDisabledError, MockMt5Gateway
from app.application.execution import DemoExecutionService
from app.application.avenger import AvengerBracketBuilder
from app.domain.market.models import MarketSession, MarketSnapshot
from tests.unit.test_erwin import account, profile, proposal


def test_demo_execution_needs_explicit_enablement() -> None:
    trade = proposal(); decision = CommanderErwinService().evaluate(trade, account(), profile(), Decimal("0.5"))
    with pytest.raises(ExecutionDisabledError):
        DemoExecutionService(MockMt5Gateway(account(), enabled=True), False, "demo").submit(trade, decision)


def test_mock_order_is_idempotent() -> None:
    trade = proposal(); decision = CommanderErwinService().evaluate(trade, account(), profile(), Decimal("0.5"))
    service = DemoExecutionService(MockMt5Gateway(account(), enabled=True), True, "demo")
    assert service.submit(trade, decision) == service.submit(trade, decision)


def test_demo_execution_rejects_cross_cycle_approval() -> None:
    trade = proposal(); decision = CommanderErwinService().evaluate(trade, account(), profile(), Decimal("0.5"))
    mismatched = decision.model_copy(update={"correlation_id": uuid4()})
    with pytest.raises(PermissionError):
        DemoExecutionService(MockMt5Gateway(account(), enabled=True), True, "demo").submit(trade, mismatched)


def test_demo_execution_submits_approved_avenger_bracket(monkeypatch) -> None:
    from app.config.settings import get_settings

    monkeypatch.setenv("XAU_AVENGER_PROFILE_MODE", "FLASH")
    get_settings.cache_clear()
    try:
        market = MarketSnapshot(
            bid=Decimal("4010.00"),
            ask=Decimal("4010.20"),
            atr=Decimal("1.00"),
            ema_fast=Decimal("4011"),
            ema_slow=Decimal("4010"),
            rsi=Decimal("60"),
            trend_strength=Decimal("5"),
            volatility_score=Decimal("7"),
            liquidity_score=Decimal("8"),
            momentum_score=Decimal("8"),
            session=MarketSession.LONDON,
        )
        plan = AvengerBracketBuilder().build(market, get_settings(), Decimal("0.25"), uuid4())
        commander = CommanderErwinService()
        buy_decision = commander.evaluate(plan.buy.proposal, account(), profile(), Decimal("0.2"))
        sell_decision = commander.evaluate(plan.sell.proposal, account(), profile(), Decimal("0.2"))
        gateway = MockMt5Gateway(account(), enabled=True)
        tickets = DemoExecutionService(gateway, True, "demo").submit_bracket(plan, buy_decision, sell_decision)
        assert tickets == "demo-buy_stop-1,demo-sell_stop-2"
        assert [order.order_type for order in gateway.orders] == ["BUY_STOP", "SELL_STOP"]
    finally:
        get_settings.cache_clear()
